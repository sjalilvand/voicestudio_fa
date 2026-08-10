"""Central scheduler.

Two structural decisions the council settled, both of which shape everything
else in this module:

**One central queue.** The original design gave every worker its own queue with
its own depth and maximum size. That produces head-of-line blocking — a task
committed to a busy worker waits while another sits idle — and then demands
work-stealing to undo. Here the queue is central and workers hold only in-flight
slots, so a task is bound to a worker at the last possible moment.

**Filter, then strategy, then tiebreak.** The original had seven user-selectable
strategies *and* a ten-factor ranked scheduler, with no rule for how they
compose — so "always use my primary" and "never use an unhealthy worker" could
each claim to be authoritative. The pipeline here is unambiguous:

    1. hard filter   — enabled, connected, consented, capable, has capacity,
                       breaker closed, not excluded, not draining.
                       A user strategy can NEVER override these.
    2. strategy      — priority-ordered or least-busy, over the survivors.
    3. tiebreak      — warm model first, then lower load, then higher priority.

Model residency is in the tiebreak rather than the strategy because it is a
latency term, not a preference: a warm model is seconds away and a cold one can
be minutes.
"""
from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from worker import deadlines as deadline_policy
from worker import task_store
from worker.breaker import Attribution
from worker.capacity import WorkerCapacity
from worker.clock import resolve
from worker.errors import ErrorClass, WorkerError
from worker.lifecycle import Attempt, PriorityClass, Task, TaskState, reconcile
from worker.pool import ConnectedWorker, WorkerPool

logger = logging.getLogger("omnivoice.worker")

# Bounded queue. Past this, submission is refused at the door with an
# actionable error rather than accepted and quietly timed out later.
_MAX_QUEUE_DEPTH = 200


class Strategy(str, enum.Enum):
    """Two strategies, not seven.

    ``PRIORITY`` expresses primary/backup: the user's preferred machine simply
    has a higher priority number. ``LEAST_BUSY`` is the default and is what
    most setups actually want. Random and round-robin collapse into each other
    once the eligibility filter has run, and lowest-latency is actively
    misleading — heartbeat round-trip is milliseconds while inference is
    seconds, so it ranks on noise.
    """

    LEAST_BUSY = "least_busy"
    PRIORITY = "priority"


class QueueFull(RuntimeError):
    """Submission refused because the queue is at its bound."""


class NoEligibleWorker(RuntimeError):
    """No connected worker can run this task."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class Assignment:
    """One task bound to one worker, ready to send."""

    task: Task
    attempt: Attempt
    worker: ConnectedWorker
    deadlines: deadline_policy.Deadlines


class Scheduler:
    """Owns the queue, the selection pipeline, and the deadline sweeper."""

    def __init__(
        self,
        pool: WorkerPool,
        *,
        strategy: Strategy = Strategy.LEAST_BUSY,
        max_queue_depth: int = _MAX_QUEUE_DEPTH,
        persist: bool = True,
    ) -> None:
        self.pool = pool
        self.strategy = strategy
        self.max_queue_depth = max_queue_depth
        self._persist = persist
        # Central queue: task_id → Task, insertion-ordered.
        self._tasks: dict[str, Task] = {}
        self._listeners: list[Callable[[str, Task], None]] = []

    # ── Persistence seam ──────────────────────────────────────────────────

    def _save(self, task: Task, *, now: Optional[float] = None) -> None:
        if self._persist:
            task_store.save(task, now=now)

    def on_change(self, callback: Callable[[str, Task], None]) -> None:
        """Subscribe to task transitions (the UI's event feed hangs off this)."""
        self._listeners.append(callback)

    def _emit(self, event: str, task: Task) -> None:
        for callback in self._listeners:
            try:
                callback(event, task)
            except Exception:
                logger.exception("Task listener failed for %s", event)

    # ── Submission ────────────────────────────────────────────────────────

    def submit(
        self,
        *,
        operation: str,
        engine: str,
        model_id: str,
        params: Optional[dict] = None,
        priority: PriorityClass = PriorityClass.INTERACTIVE,
        idempotency_key: Optional[str] = None,
        max_attempts: int = 3,
        deadline_seconds: Optional[float] = None,
        now: Optional[float] = None,
    ) -> Task:
        """Admit a task, or refuse it at the door.

        Refusing at submission is deliberate: accepting work into an unbounded
        queue means the user waits, then gets a timeout that looks like their
        hardware failed. A queue-full error names the real problem while they
        can still act on it.
        """
        stamp = resolve(now)
        if idempotency_key:
            for existing in self._tasks.values():
                if existing.idempotency_key == idempotency_key:
                    return existing
            if self._persist:
                stored = task_store.get_by_idempotency_key(idempotency_key)
                if stored is not None:
                    self._tasks.setdefault(stored.task_id, stored)
                    return stored

        if self.queue_depth >= self.max_queue_depth:
            raise QueueFull(
                f"The remote task queue is full ({self.max_queue_depth} waiting). "
                "Wait for current work to finish, or add another worker."
            )

        task = Task(
            task_id=uuid.uuid4().hex[:16],
            operation=operation,
            engine=engine,
            model_id=model_id,
            params=params or {},
            priority=priority,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            created_at=stamp,
        )
        if deadline_seconds:
            task.deadline_at = stamp + deadline_seconds
        self._tasks[task.task_id] = task
        if self._persist:
            task_store.create(task, now=stamp)
        self._emit("queued", task)
        return task

    def adopt(self, task: Task) -> None:
        """Take ownership of a task loaded from disk after a restart."""
        self._tasks[task.task_id] = task

    def restore(self) -> int:
        """Reload tasks that were live when the control plane stopped.

        They are NOT failed on the way in — unlike local jobs, the machine
        doing the work is still running. Reconciliation decides each one's fate
        when its worker reconnects.
        """
        if not self._persist:
            return 0
        restored = task_store.load_unfinished()
        for task in restored:
            self._tasks.setdefault(task.task_id, task)
        if restored:
            logger.info("Recovered %d in-flight remote task(s) after restart", len(restored))
        return len(restored)

    # ── Queue introspection ───────────────────────────────────────────────

    @property
    def queue_depth(self) -> int:
        return sum(1 for t in self._tasks.values() if t.state is TaskState.QUEUED)

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def tasks_for_worker(self, worker_id: str) -> list[Task]:
        """Live tasks this control plane believes ``worker_id`` is running.

        Sent back on reconnect as the authoritative list: anything the worker
        holds that is absent here is a zombie it must stop, and anything here
        the worker does not claim was lost while we were apart.
        """
        found = []
        for task in self._tasks.values():
            if task.state.terminal:
                continue
            attempt = task.active_attempt
            if attempt is not None and attempt.worker_id == worker_id:
                found.append(task)
        return found

    def position(self, task_id: str) -> int:
        """0-indexed place in line, or -1. Preserves the local queue's
        "2 jobs ahead of you" affordance for remote work."""
        target = self._tasks.get(task_id)
        if target is None or target.state is not TaskState.QUEUED:
            return -1
        return sum(1 for t in self._queued_order() if t.task_id != task_id and self._ranks_before(t, target))

    def _queued_order(self) -> list[Task]:
        """Interactive before batch, then FIFO inside each class."""
        return sorted(
            (t for t in self._tasks.values() if t.state is TaskState.QUEUED),
            key=lambda t: (int(t.priority), t.created_at),
        )

    @staticmethod
    def _ranks_before(a: Task, b: Task) -> bool:
        return (int(a.priority), a.created_at) < (int(b.priority), b.created_at)

    # ── Selection ─────────────────────────────────────────────────────────

    def eligible_workers(self, task: Task, *, now: Optional[float] = None) -> list[ConnectedWorker]:
        """The hard filter. No strategy may bypass any of these."""
        stamp = resolve(now)
        model_key = WorkerCapacity.slot_key(task.engine, task.model_id)
        eligible = []
        for worker in self.pool:
            if not worker.record.schedulable or worker.draining:
                continue
            if worker.stale(now=stamp):
                continue
            if worker.worker_id in task.excluded_workers:
                continue
            if not worker.supports(task.engine, task.model_id, task.operation):
                continue
            if not worker.capacity.can_accept(task.engine, task.model_id):
                continue
            if not self.pool.breakers.allows(worker.worker_id, model_key, now=stamp):
                continue
            eligible.append(worker)
        return eligible

    def _rank(self, task: Task, workers: list[ConnectedWorker]) -> list[ConnectedWorker]:
        """Strategy, then tiebreak. Warm-model affinity is the first tiebreak
        because it is worth more than any other factor here: a resident model
        is seconds away, a cold one minutes."""

        def tiebreak(worker: ConnectedWorker) -> tuple:
            return (
                0 if worker.is_warm(task.engine, task.model_id) else 1,
                worker.capacity.active_tasks,
                -worker.record.priority,
                worker.record.created_at,
            )

        if self.strategy is Strategy.PRIORITY:
            return sorted(workers, key=lambda w: (-w.record.priority, *tiebreak(w)))
        return sorted(workers, key=lambda w: (w.capacity.active_tasks, *tiebreak(w)))

    def select_worker(self, task: Task, *, now: Optional[float] = None) -> ConnectedWorker:
        """Pick the best eligible worker, or explain why there is none.

        The two "nothing available" cases are deliberately distinguished: all
        workers busy is a wait, no capable worker is a dead end, and telling a
        user to wait for something that will never happen is the error-message
        failure this project treats as a bug.
        """
        stamp = resolve(now)
        eligible = self.eligible_workers(task, now=stamp)
        if eligible:
            return self._rank(task, eligible)[0]

        capable = [
            w
            for w in self.pool
            if w.record.schedulable and w.supports(task.engine, task.model_id, task.operation)
        ]
        if not capable:
            raise NoEligibleWorker(
                f"No connected worker can run {task.engine or task.operation}. "
                "Check the worker is online and has that engine installed.",
                retryable=False,
            )
        raise NoEligibleWorker(
            "Every worker that can run this is busy or paused. The task stays queued.",
            retryable=True,
        )

    # ── Dispatch ──────────────────────────────────────────────────────────

    def next_assignment(self, *, now: Optional[float] = None) -> Optional[Assignment]:
        """Bind the highest-ranked waiting task to the best worker for it.

        Returns ``None`` when nothing can be dispatched — either the queue is
        empty or every waiting task is blocked on capacity. A task with no
        capable worker at all is failed here rather than left to age out.
        """
        stamp = resolve(now)
        for task in self._queued_order():
            try:
                worker = self.select_worker(task, now=stamp)
            except NoEligibleWorker as exc:
                if exc.retryable:
                    continue
                self._fail(
                    task,
                    WorkerError(
                        error_class=ErrorClass.CAPABILITY,
                        code="NO_CAPABLE_WORKER",
                        message=str(exc),
                        hint="Install the engine on a worker, or run this task locally.",
                    ),
                    now=stamp,
                )
                continue
            return self._bind(task, worker, now=stamp)
        return None

    def _bind(self, task: Task, worker: ConnectedWorker, *, now: float) -> Assignment:
        attempt = task.assign(worker_id=worker.worker_id, session_epoch=worker.epoch, now=now)
        worker.capacity.reserve(task.engine, task.model_id)
        worker.in_flight.add(attempt.attempt_id)

        budget = deadline_policy.for_task(
            task.operation,
            text=task.params.get("text"),
            model_resident=worker.is_warm(task.engine, task.model_id),
            model_downloaded=True,
            input_seconds=float(task.params.get("input_seconds") or 0.0),
        )
        attempt.renew_lease(budget.accept_seconds, now=now)
        self._save(task, now=now)
        self._emit("assigned", task)
        return Assignment(task=task, attempt=attempt, worker=worker, deadlines=budget)

    # ── Worker callbacks ──────────────────────────────────────────────────

    def _fenced(self, task_id: str, attempt_id: str, epoch: Optional[int]) -> Optional[Task]:
        """Resolve a task for an inbound message, dropping stale sessions."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        attempt = task.get_attempt(attempt_id)
        if attempt is None:
            return None
        if epoch is not None and attempt.session_epoch != epoch:
            logger.debug("Dropping message for %s from stale epoch %s", task_id, epoch)
            return None
        return task

    def on_accepted(
        self, task_id: str, attempt_id: str, *, epoch: Optional[int] = None, now: Optional[float] = None
    ) -> Optional[Task]:
        task = self._fenced(task_id, attempt_id, epoch)
        if task is None:
            return None
        stamp = resolve(now)
        task.accept(attempt_id, session_epoch=epoch, now=stamp)
        budget = self._budget_for(task)
        task.get_attempt(attempt_id).renew_lease(budget.model_load_seconds, now=stamp)
        self._save(task, now=stamp)
        self._emit("accepted", task)
        return task

    def on_model_loading(
        self,
        task_id: str,
        attempt_id: str,
        *,
        progress: float = -1.0,
        detail: str = "",
        epoch: Optional[int] = None,
        now: Optional[float] = None,
    ) -> Optional[Task]:
        task = self._fenced(task_id, attempt_id, epoch)
        if task is None:
            return None
        stamp = resolve(now)
        attempt = task.get_attempt(attempt_id)
        if task.state is not TaskState.MODEL_LOADING:
            task.model_loading(attempt_id, session_epoch=epoch, now=stamp)
        attempt.stage = detail or "loading model"
        # A load that is still reporting is not stuck, however long it takes.
        attempt.renew_lease(self._budget_for(task).progress_lease_seconds, now=stamp)
        self._save(task, now=stamp)
        self._emit("model_loading", task)
        return task

    def on_started(
        self, task_id: str, attempt_id: str, *, epoch: Optional[int] = None, now: Optional[float] = None
    ) -> Optional[Task]:
        task = self._fenced(task_id, attempt_id, epoch)
        if task is None:
            return None
        stamp = resolve(now)
        task.start(attempt_id, session_epoch=epoch, now=stamp)
        task.get_attempt(attempt_id).renew_lease(
            self._budget_for(task).progress_lease_seconds, now=stamp
        )
        self._save(task, now=stamp)
        self._emit("started", task)
        return task

    def on_progress(
        self,
        task_id: str,
        attempt_id: str,
        *,
        progress: float,
        stage: str = "",
        epoch: Optional[int] = None,
        now: Optional[float] = None,
    ) -> Optional[Task]:
        task = self._fenced(task_id, attempt_id, epoch)
        if task is None:
            return None
        stamp = resolve(now)
        attempt = task.get_attempt(attempt_id)
        attempt.progress = max(0.0, min(1.0, progress))
        attempt.stage = stage or attempt.stage
        attempt.renew_lease(self._budget_for(task).progress_lease_seconds, now=stamp)
        self._emit("progress", task)
        return task

    def on_result(
        self,
        task_id: str,
        attempt_id: str,
        *,
        result_ref: Optional[str] = None,
        result: Optional[dict] = None,
        epoch: Optional[int] = None,
        now: Optional[float] = None,
    ) -> tuple[bool, Optional[Task]]:
        """Commit a result. Returns ``(committed, task)``.

        The caller must acknowledge the worker in BOTH cases — a duplicate
        still needs its ack, or the worker redelivers forever — but must only
        apply the result when ``committed`` is True.

        The commit is durable before this returns, which is what makes the
        subsequent RESULT_ACK safe to send.
        """
        stamp = resolve(now)
        task = self._tasks.get(task_id)
        if task is None:
            # Unknown task: either purged, or this control plane restarted and
            # never reloaded it. If disk says it completed, ack-and-discard.
            if self._persist and task_store.is_committed(task_id):
                return False, None
            return False, None
        attempt = task.get_attempt(attempt_id)
        if attempt is None:
            return False, task
        if epoch is not None and attempt.session_epoch != epoch:
            return False, task

        committed, attempt = task.commit_result(
            attempt_id, result_ref=result_ref, session_epoch=epoch, now=stamp
        )
        worker = self.pool.get(attempt.worker_id)
        if worker is not None:
            worker.in_flight.discard(attempt_id)
            worker.capacity.release(task.engine, task.model_id)
            if committed:
                self.pool.breakers.record_success(
                    worker.worker_id,
                    WorkerCapacity.slot_key(task.engine, task.model_id),
                    now=stamp,
                )
        if committed and self._persist:
            task_store.commit_result(task, result_json=result, now=stamp)
        elif self._persist:
            self._save(task, now=stamp)
        self._emit("completed" if committed else "duplicate", task)
        return committed, task

    def on_failed(
        self,
        task_id: str,
        attempt_id: str,
        error: WorkerError,
        *,
        epoch: Optional[int] = None,
        now: Optional[float] = None,
    ) -> Optional[Task]:
        task = self._fenced(task_id, attempt_id, epoch)
        if task is None:
            return None
        stamp = resolve(now)
        attempt = task.get_attempt(attempt_id)
        worker = self.pool.get(attempt.worker_id)
        model_key = WorkerCapacity.slot_key(task.engine, task.model_id)

        task.fail_attempt(attempt_id, error, session_epoch=epoch, now=stamp)

        if worker is not None:
            worker.in_flight.discard(attempt_id)
            # A timeout leaves a GPU thread that cannot be killed, so its slot
            # is parked rather than returned (#730/#1190).
            worker.capacity.release(
                task.engine, task.model_id, zombie=error.error_class is ErrorClass.TIMEOUT
            )
            attribution, opened = self.pool.breakers.record_failure(
                worker.worker_id, model_key, error, now=stamp
            )
            if opened:
                logger.info(
                    "Circuit breaker opened for %s / %s after repeated failures",
                    worker.name,
                    model_key,
                )
            elif attribution is Attribution.INFRA:
                logger.info("Suppressing penalty for %s — fleet-wide failure detected", worker.name)

        self._save(task, now=stamp)
        self._emit("failed" if task.state.terminal else "requeued", task)
        return task

    def on_disconnected(self, worker_id: str, *, now: Optional[float] = None) -> list[Task]:
        """A worker's stream dropped. Start grace windows; fail nothing.

        This is where the duplicate-execution bug would live if a disconnect
        were treated as a failure: the worker may be seconds from delivering.
        """
        stamp = resolve(now)
        affected: list[Task] = []
        for task in self._tasks.values():
            attempt = task.active_attempt
            if attempt is None or attempt.worker_id != worker_id:
                continue
            grace = deadline_policy.default_grace_seconds(task.operation)
            task.mark_disconnected(attempt.attempt_id, grace_seconds=grace, now=stamp)
            affected.append(task)
            self._save(task, now=stamp)
            self._emit("worker_lost", task)
        self.pool.disconnect(worker_id)
        return affected

    def on_reconnected(
        self, worker_id: str, *, in_flight: set[str], now: Optional[float] = None
    ) -> list[str]:
        """Reconcile against what the worker says it is running.

        Returns attempt ids the worker should cancel — work we have already
        written off, which it must stop burning a GPU on.
        """
        stamp = resolve(now)
        zombies: list[str] = []
        for task in list(self._tasks.values()):
            if task.state.terminal:
                continue
            action = reconcile(task, worker_id=worker_id, worker_in_flight=in_flight, now=stamp)
            if action == "cancel_zombie":
                zombies.extend(
                    a for a in in_flight if (k := task.get_attempt(a)) and k.state.terminal
                )
            self._save(task, now=stamp)
        return zombies

    def cancel(self, task_id: str, *, reason: str = "cancelled", now: Optional[float] = None) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.state.terminal:
            return False
        stamp = resolve(now)
        attempt = task.active_attempt
        task.cancel(reason=reason, now=stamp)
        if attempt is not None:
            worker = self.pool.get(attempt.worker_id)
            if worker is not None:
                worker.in_flight.discard(attempt.attempt_id)
                worker.capacity.release(task.engine, task.model_id)
        self._save(task, now=stamp)
        self._emit("cancelled", task)
        return True

    # ── Sweeper ───────────────────────────────────────────────────────────

    def sweep(self, *, now: Optional[float] = None) -> list[Task]:
        """Enforce leases, grace windows, and task deadlines.

        Called on a timer. Everything time-based happens here rather than being
        scattered across callbacks, so there is one place to reason about what
        expires and in what order.
        """
        stamp = resolve(now)
        changed: list[Task] = []

        for worker in self.pool.stale_workers(now=stamp):
            logger.info("Worker %s missed its heartbeats — treating as disconnected", worker.name)
            changed.extend(self.on_disconnected(worker.worker_id, now=stamp))

        for task in list(self._tasks.values()):
            if task.state.terminal:
                continue
            attempt = task.active_attempt

            if attempt is not None and attempt.grace_expired(now=stamp):
                task.lose_attempt(attempt.attempt_id, now=stamp)
                self._release(task, attempt)
                changed.append(task)
                self._save(task, now=stamp)
                self._emit("attempt_lost", task)
                continue

            if attempt is not None and attempt.disconnected_at is None and attempt.lease_expired(now=stamp):
                self._expire(task, attempt, now=stamp)
                changed.append(task)
                continue

            if task.deadline_exceeded(now=stamp) and task.state is TaskState.QUEUED:
                self._fail(
                    task,
                    WorkerError(
                        error_class=ErrorClass.TIMEOUT,
                        code="TASK_DEADLINE_EXCEEDED",
                        message="The task waited for an available worker past its deadline.",
                        hint="Add a worker, or run this task locally.",
                    ),
                    now=stamp,
                )
                changed.append(task)
        return changed

    def _expire(self, task: Task, attempt: Attempt, *, now: float) -> None:
        """A live attempt stopped reporting. Silence, not slowness, fails."""
        code = {
            TaskState.ASSIGNED: "ACCEPT_TIMEOUT",
            TaskState.MODEL_LOADING: "MODEL_LOAD_TIMEOUT",
            TaskState.RESULT_UPLOADING: "RESULT_DELIVERY_TIMEOUT",
        }.get(task.state, "PROGRESS_LEASE_EXPIRED")
        self.on_failed(
            task.task_id,
            attempt.attempt_id,
            WorkerError(
                error_class=ErrorClass.TIMEOUT,
                code=code,
                message="The worker stopped reporting progress.",
                hint="It will be retried on another worker if one is available.",
            ),
            epoch=attempt.session_epoch,
            now=now,
        )

    def _release(self, task: Task, attempt: Attempt) -> None:
        worker = self.pool.get(attempt.worker_id)
        if worker is not None:
            worker.in_flight.discard(attempt.attempt_id)
            worker.capacity.release(task.engine, task.model_id)

    def _fail(self, task: Task, error: WorkerError, *, now: float) -> None:
        task.error = error
        task.state = TaskState.FAILED if error.error_class is not ErrorClass.TIMEOUT else TaskState.TIMEOUT
        task.finished_at = now
        self._save(task, now=now)
        self._emit("failed", task)

    def _budget_for(self, task: Task) -> deadline_policy.Deadlines:
        attempt = task.active_attempt
        worker = self.pool.get(attempt.worker_id) if attempt else None
        return deadline_policy.for_task(
            task.operation,
            text=task.params.get("text"),
            model_resident=bool(worker and worker.is_warm(task.engine, task.model_id)),
            input_seconds=float(task.params.get("input_seconds") or 0.0),
        )


__all__ = ["Assignment", "NoEligibleWorker", "QueueFull", "Scheduler", "Strategy"]
