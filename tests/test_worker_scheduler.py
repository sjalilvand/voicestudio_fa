"""Scheduler: admission, the selection pipeline, dispatch, and the sweeper.

The pipeline under test is filter → strategy → tiebreak. The property that
matters most: a user-selected strategy can reorder *preferences* but can never
reach past the hard filter to pick a worker that is offline, incapable, full,
or paused.
"""
from __future__ import annotations

import pytest

from worker.capacity import ModelSlot
from worker.errors import ErrorClass, WorkerError
from worker.identity import issue_session
from worker.lifecycle import PriorityClass, TaskState
from worker.pool import WorkerPool
from worker.registry import RemoteWorker
from worker.scheduler import NoEligibleWorker, QueueFull, Scheduler, Strategy

ENGINE, MODEL, OP = "indextts", "IndexTTS-2", "tts"
MODEL_KEY = f"{ENGINE}:{MODEL}"


def _record(
    worker_id: str,
    *,
    priority: int = 50,
    consent: bool = True,
    operations: list[str] | None = None,
) -> RemoteWorker:
    return RemoteWorker(
        id=worker_id,
        name=worker_id,
        key_id=f"key-{worker_id}",
        public_key=b"\x00" * 32,
        priority=priority,
        capabilities=[
            {
                "engine": ENGINE,
                "model_id": MODEL,
                "operations": operations or [OP],
                "supported": True,
                "installed": True,
                "downloaded": True,
            }
        ],
        consent_granted_at=1.0 if consent else None,
        created_at=1.0,
    )


def _pool(*workers, slots: int = 2, now: float = 1000.0) -> WorkerPool:
    pool = WorkerPool()
    for record in workers:
        pool.connect(
            record,
            session=issue_session(worker_id=record.id, key_id=record.key_id, epoch=1, now=now),
            epoch=1,
            max_concurrent_tasks=slots,
            backend="cuda",
            now=now,
        )
    return pool


def _scheduler(pool: WorkerPool, **kw) -> Scheduler:
    return Scheduler(pool, persist=False, **kw)


def _submit(sched: Scheduler, **kw):
    defaults = dict(operation=OP, engine=ENGINE, model_id=MODEL, now=1000.0)
    defaults.update(kw)
    return sched.submit(**defaults)


# ── Admission ──────────────────────────────────────────────────────────────


def test_submit_queues_a_task():
    sched = _scheduler(_pool(_record("w1")))
    task = _submit(sched)
    assert task.state is TaskState.QUEUED
    assert sched.queue_depth == 1


def test_idempotency_key_deduplicates_client_retries():
    """A client HTTP retry must not produce a second render of the same text."""
    sched = _scheduler(_pool(_record("w1")))
    first = _submit(sched, idempotency_key="abc")
    second = _submit(sched, idempotency_key="abc")
    assert first.task_id == second.task_id
    assert sched.queue_depth == 1


def test_queue_is_bounded_and_refuses_at_the_door():
    """Accepting into an unbounded queue means the user waits, then gets a
    timeout that looks like their hardware failed."""
    sched = _scheduler(_pool(_record("w1")), max_queue_depth=2)
    _submit(sched)
    _submit(sched)
    with pytest.raises(QueueFull, match="full"):
        _submit(sched)


def test_queue_full_error_is_actionable():
    sched = _scheduler(_pool(_record("w1")), max_queue_depth=1)
    _submit(sched)
    with pytest.raises(QueueFull) as exc:
        _submit(sched)
    assert "add another worker" in str(exc.value).lower()


# ── Ordering ───────────────────────────────────────────────────────────────


def test_interactive_outranks_batch():
    sched = _scheduler(_pool(_record("w1")))
    batch = _submit(sched, priority=PriorityClass.BATCH)
    interactive = _submit(sched, priority=PriorityClass.INTERACTIVE)
    assert sched.next_assignment(now=1000.0).task.task_id == interactive.task_id
    assert batch.state is TaskState.QUEUED


def test_same_class_is_fifo():
    sched = _scheduler(_pool(_record("w1")))
    first = _submit(sched, now=1000.0)
    _submit(sched, now=1001.0)
    assert sched.next_assignment(now=1002.0).task.task_id == first.task_id


def test_queue_position_is_reported():
    """Preserves the local queue's "2 jobs ahead of you" affordance."""
    sched = _scheduler(_pool(_record("w1")))
    a = _submit(sched, now=1000.0)
    b = _submit(sched, now=1001.0)
    assert sched.position(a.task_id) == 0
    assert sched.position(b.task_id) == 1


# ── Hard filter ────────────────────────────────────────────────────────────


def test_disabled_worker_is_never_selected():
    record = _record("w1")
    record.enabled = False
    sched = _scheduler(_pool(record))
    with pytest.raises(NoEligibleWorker):
        sched.select_worker(_submit(sched), now=1000.0)


def test_worker_without_consent_is_never_selected():
    """Audio must not leave the machine for a worker the user never approved."""
    sched = _scheduler(_pool(_record("w1", consent=False)))
    with pytest.raises(NoEligibleWorker):
        sched.select_worker(_submit(sched), now=1000.0)


def test_incapable_worker_is_never_selected():
    sched = _scheduler(_pool(_record("w1")))
    task = _submit(sched, engine="cosyvoice", model_id="CosyVoice2")
    with pytest.raises(NoEligibleWorker) as exc:
        sched.select_worker(task, now=1000.0)
    assert exc.value.retryable is False


def test_excluded_worker_is_never_reselected():
    sched = _scheduler(_pool(_record("w1")))
    task = _submit(sched)
    task.excluded_workers.add("w1")
    with pytest.raises(NoEligibleWorker):
        sched.select_worker(task, now=1000.0)


def test_open_breaker_removes_a_worker():
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    for _ in range(3):
        pool.breakers.record_failure(
            "w1", MODEL_KEY, WorkerError(error_class=ErrorClass.TRANSIENT, code="X", message="x"), now=1000.0
        )
    with pytest.raises(NoEligibleWorker) as exc:
        sched.select_worker(_submit(sched), now=1000.0)
    assert exc.value.retryable is True


def test_stale_worker_is_removed():
    """Half-open TCP looks exactly like a healthy idle connection."""
    sched = _scheduler(_pool(_record("w1"), now=1000.0))
    with pytest.raises(NoEligibleWorker):
        sched.select_worker(_submit(sched), now=1000.0 + 500)


def test_draining_worker_takes_no_new_work():
    pool = _pool(_record("w1"))
    pool.get("w1").draining = True
    sched = _scheduler(pool)
    with pytest.raises(NoEligibleWorker):
        sched.select_worker(_submit(sched), now=1000.0)


def test_full_worker_is_removed_but_stays_retryable():
    pool = _pool(_record("w1"), slots=1)
    sched = _scheduler(pool)
    _submit(sched)
    sched.next_assignment(now=1000.0)
    with pytest.raises(NoEligibleWorker) as exc:
        sched.select_worker(_submit(sched), now=1000.0)
    assert exc.value.retryable is True


def test_busy_and_incapable_are_different_errors():
    """Telling a user to wait for something that will never happen is the
    error-message failure this project treats as a bug."""
    pool = _pool(_record("w1"), slots=1)
    sched = _scheduler(pool)
    _submit(sched)
    sched.next_assignment(now=1000.0)

    with pytest.raises(NoEligibleWorker) as busy:
        sched.select_worker(_submit(sched), now=1000.0)
    with pytest.raises(NoEligibleWorker) as incapable:
        sched.select_worker(_submit(sched, engine="nope"), now=1000.0)

    assert busy.value.retryable is True
    assert incapable.value.retryable is False
    assert "busy" in str(busy.value).lower()
    assert "install" in str(incapable.value).lower()


# ── Strategy and tiebreak ──────────────────────────────────────────────────


def test_priority_strategy_prefers_the_primary():
    pool = _pool(_record("low", priority=10), _record("high", priority=90))
    sched = _scheduler(pool, strategy=Strategy.PRIORITY)
    assert sched.select_worker(_submit(sched), now=1000.0).worker_id == "high"


def test_least_busy_is_the_default():
    pool = _pool(_record("w1"), _record("w2"))
    sched = _scheduler(pool)
    pool.get("w1").capacity.reserve(ENGINE, MODEL)
    assert sched.select_worker(_submit(sched), now=1000.0).worker_id == "w2"


def test_strategy_cannot_override_the_hard_filter():
    """The §14-vs-§19 conflict: a user's 'always use my primary' must not be
    able to select a paused or offline worker."""
    pool = _pool(_record("primary", priority=100), _record("backup", priority=10))
    sched = _scheduler(pool, strategy=Strategy.PRIORITY)
    for _ in range(3):
        pool.breakers.record_failure(
            "primary",
            MODEL_KEY,
            WorkerError(error_class=ErrorClass.TRANSIENT, code="X", message="x"),
            now=1000.0,
        )
    assert sched.select_worker(_submit(sched), now=1000.0).worker_id == "backup"


def test_warm_model_wins_the_tiebreak():
    """A resident model is seconds away; a cold one can be minutes."""
    pool = _pool(_record("cold"), _record("warm"))
    pool.get("warm").capacity.resident_models = {MODEL_KEY}
    sched = _scheduler(pool)
    assert sched.select_worker(_submit(sched), now=1000.0).worker_id == "warm"


def test_load_beats_warmth_when_a_warm_worker_is_saturated():
    pool = _pool(_record("warm"), _record("cold"), slots=1)
    pool.get("warm").capacity.resident_models = {MODEL_KEY}
    sched = _scheduler(pool)
    _submit(sched)
    first = sched.next_assignment(now=1000.0)
    assert first.worker.worker_id == "warm"
    assert sched.select_worker(_submit(sched), now=1000.0).worker_id == "cold"


def test_per_model_slot_limit_is_respected():
    pool = _pool(_record("w1"), slots=8)
    pool.get("w1").capacity.slots[MODEL_KEY] = ModelSlot(
        engine=ENGINE, model_id=MODEL, derived_concurrency=1
    )
    sched = _scheduler(pool)
    _submit(sched)
    sched.next_assignment(now=1000.0)
    with pytest.raises(NoEligibleWorker):
        sched.select_worker(_submit(sched), now=1000.0)


# ── Dispatch ───────────────────────────────────────────────────────────────


def test_assignment_reserves_capacity_and_sets_deadlines():
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    _submit(sched)
    assignment = sched.next_assignment(now=1000.0)

    assert assignment.task.state is TaskState.ASSIGNED
    assert pool.get("w1").capacity.active_tasks == 1
    assert assignment.attempt.attempt_id in pool.get("w1").in_flight
    assert assignment.deadlines.accept_seconds > 0


def test_no_capable_worker_fails_the_task_rather_than_ageing_it_out():
    sched = _scheduler(_pool(_record("w1")))
    task = _submit(sched, engine="nope")
    assert sched.next_assignment(now=1000.0) is None
    assert task.state is TaskState.FAILED
    assert task.error.code == "NO_CAPABLE_WORKER"


def test_all_busy_leaves_the_task_queued():
    pool = _pool(_record("w1"), slots=1)
    sched = _scheduler(pool)
    _submit(sched)
    queued = _submit(sched)
    sched.next_assignment(now=1000.0)
    assert sched.next_assignment(now=1000.0) is None
    assert queued.state is TaskState.QUEUED


def test_happy_path_completes_and_releases_capacity():
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)

    sched.on_accepted(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1001.0)
    sched.on_started(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1002.0)
    committed, task = sched.on_result(
        a.task.task_id, a.attempt.attempt_id, result_ref="out.wav", epoch=1, now=1003.0
    )

    assert committed is True
    assert task.state is TaskState.COMPLETED
    assert pool.get("w1").capacity.active_tasks == 0


def test_duplicate_result_is_acked_but_not_applied():
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)
    sched.on_accepted(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1001.0)
    sched.on_started(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1002.0)
    sched.on_result(a.task.task_id, a.attempt.attempt_id, result_ref="first", epoch=1, now=1003.0)

    committed, task = sched.on_result(
        a.task.task_id, a.attempt.attempt_id, result_ref="second", epoch=1, now=1004.0
    )
    assert committed is False
    assert task.result_ref == "first"


def test_stale_epoch_messages_are_dropped():
    sched = _scheduler(_pool(_record("w1")))
    _submit(sched)
    a = sched.next_assignment(now=1000.0)
    assert sched.on_accepted(a.task.task_id, a.attempt.attempt_id, epoch=99, now=1001.0) is None
    assert a.task.state is TaskState.ASSIGNED


# ── Failures and retry ─────────────────────────────────────────────────────


def test_failure_requeues_and_excludes_the_worker():
    pool = _pool(_record("w1"), _record("w2"))
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)

    sched.on_failed(
        a.task.task_id,
        a.attempt.attempt_id,
        WorkerError(error_class=ErrorClass.TRANSIENT, code="ENGINE_CRASHED", message="boom"),
        epoch=1,
        now=1001.0,
    )

    assert a.task.state is TaskState.QUEUED
    second = sched.next_assignment(now=1002.0)
    assert second.worker.worker_id != a.worker.worker_id


def test_capacity_rejection_does_not_exclude_or_charge():
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)

    sched.on_failed(
        a.task.task_id,
        a.attempt.attempt_id,
        WorkerError(error_class=ErrorClass.CAPACITY, code="WORKER_AT_CAPACITY", message="full"),
        epoch=1,
        now=1001.0,
    )

    assert a.task.excluded_workers == set()
    assert pool.breakers.allows("w1", MODEL_KEY, now=1001.0) is True


def test_timeout_parks_a_zombie_slot():
    """The GPU thread survives the timeout, so its capacity does not return."""
    pool = _pool(_record("w1"), slots=2)
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)

    sched.on_failed(
        a.task.task_id,
        a.attempt.attempt_id,
        WorkerError(error_class=ErrorClass.TIMEOUT, code="EXECUTION_TIMEOUT", message="slow"),
        epoch=1,
        now=1001.0,
    )

    assert pool.get("w1").capacity.zombie_tasks == 1
    assert pool.get("w1").capacity.available_slots == 1


# ── Disconnect and reconciliation ──────────────────────────────────────────


def test_disconnect_starts_a_grace_window_without_failing():
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)
    sched.on_accepted(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1001.0)
    sched.on_started(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1002.0)

    affected = sched.on_disconnected("w1", now=1003.0)

    assert len(affected) == 1
    assert a.task.state is TaskState.RUNNING
    assert a.attempt.grace_expires_at is not None


def test_grace_expiry_requeues_and_frees_the_slot():
    pool = _pool(_record("w1"), _record("w2"))
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)
    sched.on_accepted(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1001.0)
    sched.on_started(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1002.0)
    sched.on_disconnected("w1", now=1003.0)

    sched.sweep(now=1003.0 + 600)

    assert a.task.state is TaskState.QUEUED
    assert "w1" in a.task.excluded_workers


def test_result_arriving_inside_the_grace_window_still_commits():
    """No duplicate execution ever happened — this is the whole point."""
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)
    sched.on_accepted(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1001.0)
    sched.on_started(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1002.0)
    sched.on_disconnected("w1", now=1003.0)

    committed, task = sched.on_result(
        a.task.task_id, a.attempt.attempt_id, result_ref="out.wav", epoch=1, now=1010.0
    )

    assert committed is True
    assert task.attempt_count == 1


def test_reconnect_flags_zombies_for_cancellation():
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)
    sched.on_accepted(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1001.0)
    sched.on_started(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1002.0)
    sched.on_disconnected("w1", now=1003.0)
    sched.sweep(now=1003.0 + 600)

    zombies = sched.on_reconnected("w1", in_flight={a.attempt.attempt_id}, now=2000.0)
    assert a.attempt.attempt_id in zombies


# ── Sweeper ────────────────────────────────────────────────────────────────


def test_unaccepted_assignment_times_out():
    pool = _pool(_record("w1"), _record("w2"))
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)

    sched.sweep(now=1000.0 + a.deadlines.accept_seconds + 1)

    assert a.task.state is TaskState.QUEUED
    assert a.attempt.error.code == "ACCEPT_TIMEOUT"


def test_a_reporting_task_is_never_swept():
    """Silence is the failure signal, not slowness."""
    pool = _pool(_record("w1", operations=["dub"]))
    sched = _scheduler(pool)
    _submit(sched, operation="dub")
    a = sched.next_assignment(now=1000.0)
    sched.on_accepted(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1001.0)
    sched.on_started(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1002.0)

    clock = 1002.0
    for _ in range(60):
        clock += 60.0
        sched.on_progress(a.task.task_id, a.attempt.attempt_id, progress=0.5, epoch=1, now=clock)
        sched.sweep(now=clock)

    assert a.task.state is TaskState.RUNNING


def test_stale_heartbeat_disconnects_a_worker():
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)
    sched.on_accepted(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1001.0)
    sched.on_started(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1002.0)

    sched.sweep(now=1002.0 + 200)

    assert pool.get("w1") is None
    assert a.attempt.grace_expires_at is not None


def test_queued_task_past_its_deadline_fails_with_a_clear_reason():
    sched = _scheduler(_pool(_record("w1"), slots=1))
    _submit(sched)
    sched.next_assignment(now=1000.0)
    waiting = _submit(sched, deadline_seconds=30)

    sched.sweep(now=1100.0)

    assert waiting.state is TaskState.TIMEOUT
    assert waiting.error.code == "TASK_DEADLINE_EXCEEDED"


# ── Cancellation ───────────────────────────────────────────────────────────


def test_cancel_releases_capacity():
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    task = _submit(sched)
    sched.next_assignment(now=1000.0)

    assert sched.cancel(task.task_id, now=1001.0) is True
    assert task.state is TaskState.CANCELLED
    assert pool.get("w1").capacity.active_tasks == 0


def test_cancelling_a_finished_task_is_a_no_op():
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    _submit(sched)
    a = sched.next_assignment(now=1000.0)
    sched.on_accepted(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1001.0)
    sched.on_started(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1002.0)
    sched.on_result(a.task.task_id, a.attempt.attempt_id, result_ref="r", epoch=1, now=1003.0)

    assert sched.cancel(a.task.task_id, now=1004.0) is False


# ── Events ─────────────────────────────────────────────────────────────────


def test_transitions_are_broadcast():
    pool = _pool(_record("w1"))
    sched = _scheduler(pool)
    seen: list[str] = []
    sched.on_change(lambda event, _task: seen.append(event))

    _submit(sched)
    a = sched.next_assignment(now=1000.0)
    sched.on_accepted(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1001.0)
    sched.on_started(a.task.task_id, a.attempt.attempt_id, epoch=1, now=1002.0)
    sched.on_result(a.task.task_id, a.attempt.attempt_id, result_ref="r", epoch=1, now=1003.0)

    assert seen == ["queued", "assigned", "accepted", "started", "completed"]


def test_a_broken_listener_cannot_break_scheduling():
    sched = _scheduler(_pool(_record("w1")))
    sched.on_change(lambda *_: 1 / 0)
    _submit(sched)
    assert sched.next_assignment(now=1000.0) is not None
