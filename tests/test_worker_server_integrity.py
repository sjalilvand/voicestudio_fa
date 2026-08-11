"""Control-plane boundary integrity.

Every case here is a way a finished render could be lost, misplaced, or written
somewhere it was never meant to go — at the one layer where the peer is remote
and everything it says is untrusted input. The frames are driven straight into
the servicer rather than through a real stream: what is under test is the
translation from wire to scheduler, not gRPC.
"""
from __future__ import annotations

import os
import sqlite3

import pytest
import pytest_asyncio

from worker import identity, registry, task_store
from worker.identity import WorkerKeypair
from worker.lifecycle import AttemptState, TaskState
from worker.pool import WorkerPool
from worker.protocol.gen import worker_v1_pb2 as pb
from worker.scheduler import Scheduler
from worker.transport import codec
from worker.transport.server import WorkerServicer

ENGINE, MODEL, OP = "indextts", "IndexTTS-2", "tts"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Throwaway DB, patched where the stores actually read it."""
    from worker import registry as reg

    db_globals = reg.db_conn.__wrapped__.__globals__
    path = str(tmp_path / "userdata.db")
    with sqlite3.connect(path) as conn:
        conn.executescript(db_globals["_BASE_SCHEMA"])
    monkeypatch.setitem(db_globals, "DB_PATH", path)
    return path


class _Context:
    """Just enough of a gRPC servicer context for Register."""

    def peer(self) -> str:
        return "ipv4:127.0.0.1:5555"

    def invocation_metadata(self):
        return ()


def _capabilities() -> list[dict]:
    return [
        {
            "engine": ENGINE,
            "model_id": MODEL,
            "operations": [OP],
            "supported": True,
            "installed": True,
            "downloaded": True,
            "resident": False,
            "backend": "cuda",
            "free_memory_bytes": 24 * 1024**3,
        }
    ]


class _Plane:
    """A servicer with one enrolled worker, driven frame by frame."""

    def __init__(self, tmp_path):
        self.artifact_dir = str(tmp_path / "artifacts")
        self.pool = WorkerPool()
        self.scheduler = Scheduler(self.pool)
        self.servicer = WorkerServicer(
            self.scheduler, self.pool, artifact_dir=self.artifact_dir
        )
        self.keypair = WorkerKeypair.generate()
        self.worker_id = ""
        self.epoch = 0

    async def register(self, *, in_flight=(), completed_unacked=()) -> pb.RegisterResponse:
        """Join on first call, prove key possession on every later one."""
        token = ""
        if not self.worker_id:
            token = registry.create_enrollment(
                endpoint="localhost:1", cert_fingerprint="fp"
            ).encode()
        challenge, nonce = identity.new_challenge(), identity.new_challenge()
        signature = self.keypair.sign(
            identity.challenge_message(
                challenge=challenge,
                worker_id=self.worker_id,
                session_epoch=self.epoch,
                nonce=nonce,
            )
        )
        response = await self.servicer.Register(
            pb.RegisterRequest(
                envelope=pb.Envelope(sequence=self.epoch),
                protocol_version_min=1,
                protocol_version_max=1,
                enrollment_token=token,
                worker_id=self.worker_id,
                public_key=self.keypair.public_bytes(),
                challenge=challenge,
                challenge_signature=signature,
                nonce=nonce,
                key_id=self.keypair.key_id,
                host=codec.host_to_pb({"hostname": "gpu2", "os": "linux", "arch": "x86_64"}),
                capabilities=[codec.capability_to_pb(c) for c in _capabilities()],
                max_concurrent_tasks=2,
                in_flight=list(in_flight),
                completed_unacked=list(completed_unacked),
            ),
            _Context(),
        )
        assert not response.error.code, response.error.code
        self.worker_id = response.worker_id
        self.epoch = response.session_epoch
        return response

    @property
    def session(self):
        return self.servicer._sessions[self.worker_id]

    @property
    def outbox(self) -> list[pb.ServerMessage]:
        queue = self.session.outbox
        return list(queue._queue)

    def assign(self):
        """Submit one task and bind it to the connected worker."""
        task = self.scheduler.submit(operation=OP, engine=ENGINE, model_id=MODEL)
        assignment = self.scheduler.next_assignment()
        assert assignment is not None
        return task, assignment.attempt

    async def send(self, message: pb.WorkerMessage) -> None:
        await self.servicer._handle(self.session, message)


@pytest_asyncio.fixture
async def plane(tmp_path, db):
    p = _Plane(tmp_path)
    await p.register()
    return p


def _result(ref, *, payload=b"", artifact_id="") -> pb.WorkerMessage:
    artifacts = [pb.ArtifactRef(artifact_id=artifact_id)] if artifact_id else []
    return pb.WorkerMessage(
        result=pb.TaskResult(
            ref=ref,
            inline_payload=payload,
            artifacts=artifacts,
            result_json='{"ok": true}',
        )
    )


# ── B13: artifact paths are minted, never assembled from the wire ──────────


@pytest.mark.asyncio
async def test_inline_result_never_writes_outside_the_artifact_directory(plane, tmp_path):
    """os.path.join drops its prefix on an absolute component, so a worker that
    names its own task could write anywhere the app can."""
    escape = tmp_path / "escape"
    for task_id in ("../../../..", str(escape), "/tmp"):
        await plane.send(
            _result(
                codec.task_ref(task_id, "../../pwned", plane.epoch),
                payload=b"owned",
            )
        )

    assert not escape.exists()
    assert not (tmp_path / "pwned.bin").exists()
    assert os.listdir(plane.artifact_dir) == []


@pytest.mark.asyncio
async def test_an_inline_result_lands_under_its_own_attempt(plane):
    task, attempt = plane.assign()

    await plane.send(_result(codec.ref_for(attempt), payload=b"audio"))

    expected = os.path.join(plane.artifact_dir, task.task_id, f"{attempt.attempt_id}.bin")
    assert task.result_ref == expected
    assert open(expected, "rb").read() == b"audio"


@pytest.mark.asyncio
async def test_an_absolute_artifact_reference_is_refused(plane):
    """The uploaded-artifact path is a reference into our store, not a path."""
    task, attempt = plane.assign()

    await plane.send(_result(codec.ref_for(attempt), artifact_id="/etc/passwd"))

    assert task.state is TaskState.COMPLETED
    assert task.result_ref is None


@pytest.mark.asyncio
async def test_a_result_for_another_workers_attempt_is_not_stored(plane, tmp_path):
    """Attempt ownership gates the write, so a second worker cannot overwrite
    the attempt that is about to win."""
    task, attempt = plane.assign()
    plane.session.worker_id = "someone-else"

    await plane.send(_result(codec.ref_for(attempt), payload=b"theirs"))

    assert not os.path.exists(
        os.path.join(plane.artifact_dir, task.task_id, f"{attempt.attempt_id}.bin")
    )
    # Withholding the write is not enough on its own. The commit ran anyway,
    # marking the task done with no artifact — so the owning worker's real
    # delivery arrived as a duplicate and its audio was thrown away. Asserting
    # only the absent file let that through.
    assert task.state is not TaskState.COMPLETED, "a foreign frame committed the task"
    assert plane.outbox == [], "acking licences the wrong worker to forget"


@pytest.mark.asyncio
async def test_liveness_survives_the_reconnect_that_interrupts_it(plane):
    """A worker that drops mid-render and resumes must still be able to say so.

    The regression: task frames were fenced against the *live* session epoch,
    which ``begin_session`` bumps on every reconnect — while the worker keeps
    echoing the ref stamped at dispatch. So every keepalive after a resume was
    silently discarded and the control plane expired a task whose GPU was
    still rendering it, reporting it as silence.
    """
    task, attempt = plane.assign()
    ref = codec.ref_for(attempt)
    plane.scheduler.on_accepted(task.task_id, attempt.attempt_id, epoch=ref.session_epoch)
    plane.scheduler.on_started(task.task_id, attempt.attempt_id, epoch=ref.session_epoch)

    before = attempt.lease_expires_at
    # A resuming worker declares what it is still holding; that is what keeps
    # the attempt alive across the gap instead of reconciling it away as LOST.
    await plane.register(in_flight=[ref])  # same worker, new session epoch
    assert plane.epoch != ref.session_epoch, "the reconnect must move the session on"

    await plane.send(
        pb.WorkerMessage(progress=pb.TaskProgress(ref=ref, keepalive=True, progress=0.0))
    )

    assert attempt.lease_expires_at > before, "the keepalive was fenced away"


@pytest.mark.asyncio
async def test_a_failure_after_a_reconnect_is_not_swallowed(plane):
    """Same fence, worse consequence: the worker's own error report vanished
    and the task died of silence instead of the reason it actually had."""
    task, attempt = plane.assign()
    ref = codec.ref_for(attempt)
    plane.scheduler.on_accepted(task.task_id, attempt.attempt_id, epoch=ref.session_epoch)
    plane.scheduler.on_started(task.task_id, attempt.attempt_id, epoch=ref.session_epoch)
    await plane.register(in_flight=[ref])

    await plane.send(
        pb.WorkerMessage(
            failed=pb.TaskFailed(
                ref=ref,
                error=pb.Error(code="CUDA_OOM", message="out of memory"),
            )
        )
    )

    assert attempt.state is not AttemptState.RUNNING, "the failure never landed"
    assert attempt.error is not None and attempt.error.code == "CUDA_OOM", (
        "the task would have died of PROGRESS_LEASE_EXPIRED instead of the "
        "reason the worker actually reported"
    )


@pytest.mark.asyncio
async def test_reads_and_writes_share_one_containment_rule(plane):
    """The asymmetry that made this bug possible was two implementations of
    the same rule, one of which was missing."""
    for artifact_id in ("", "../../../../etc/passwd", "..\\..\\windows\\win.ini"):
        assert plane.servicer._resolve_input(artifact_id) is None
        assert plane.servicer._contained_artifact(artifact_id) is None


# ── B10: redelivery survives the reconnect that carries it ────────────────


@pytest.mark.asyncio
async def test_register_keeps_an_unacknowledged_result_alive(plane):
    """The worker holds the only copy. Reconciling it away as LOST while it is
    redelivering is the largest silent-loss path in the system."""
    task, attempt = plane.assign()

    await plane.register(completed_unacked=[codec.ref_for(attempt)])

    assert task.get_attempt(attempt.attempt_id).state is not AttemptState.LOST
    assert task.state is not TaskState.QUEUED


@pytest.mark.asyncio
async def test_a_result_from_a_replaced_epoch_still_commits(plane):
    """A result is a statement about a past epoch by construction: it was
    assigned in the session the reconnect just replaced."""
    task, attempt = plane.assign()
    stale_ref = codec.ref_for(attempt)

    await plane.register(completed_unacked=[stale_ref])
    assert stale_ref.session_epoch != plane.epoch, "the reconnect must move the session on"
    await plane.send(_result(stale_ref, payload=b"audio"))

    assert task.state is TaskState.COMPLETED
    assert [m.result_ack.ref.task_id for m in plane.outbox] == [task.task_id]


@pytest.mark.asyncio
async def test_a_result_this_plane_cannot_place_is_not_acknowledged(plane):
    """An ack is the worker's licence to forget. Granting it for a frame we
    dropped destroys the render."""
    await plane.send(_result(codec.task_ref("no-such-task", "no-such-attempt", plane.epoch)))

    assert plane.outbox == []


@pytest.mark.asyncio
async def test_a_duplicate_result_is_acknowledged(plane):
    """Redelivery of work that already committed is not wrong, it just lost —
    without an ack the worker redelivers forever."""
    task, attempt = plane.assign()
    ref = codec.ref_for(attempt)
    await plane.send(_result(ref, payload=b"audio"))

    await plane.send(_result(ref, payload=b"audio"))

    assert task.state is TaskState.COMPLETED
    assert len(plane.outbox) == 2


@pytest.mark.asyncio
async def test_a_result_for_a_task_this_plane_forgot_is_acknowledged(plane):
    """After a restart the task graph is gone but the commit is on disk, and
    that fact is a durable verdict."""
    task, attempt = plane.assign()
    ref = codec.ref_for(attempt)
    await plane.send(_result(ref, payload=b"audio"))
    assert task_store.is_committed(task.task_id) is True
    plane.scheduler._tasks.clear()
    plane.session.outbox._queue.clear()

    await plane.send(_result(ref, payload=b"audio"))

    assert len(plane.outbox) == 1


# ── B12: one bad frame is not a broken session ────────────────────────────


@pytest.mark.asyncio
async def test_an_illegal_frame_does_not_end_the_read_loop(plane):
    """A late or out-of-order frame raises from the domain. Letting that end
    the reader disconnects a worker that is mid-render."""
    task, attempt = plane.assign()
    await plane.send(_result(codec.ref_for(attempt), payload=b"audio"))
    late = pb.WorkerMessage(accepted=pb.TaskAccepted(ref=codec.ref_for(attempt)))
    beat = pb.WorkerMessage(heartbeat=pb.Heartbeat(active_tasks=3, available_slots=1))

    async def frames():
        yield late
        yield beat

    await plane.servicer._read_loop(plane.session, frames())

    assert plane.pool.get(plane.worker_id).capacity.active_tasks == 3
    assert task.state is TaskState.COMPLETED


# ── B1: the lease is the scheduler's arithmetic, not the transport's ──────


@pytest.mark.asyncio
@pytest.mark.parametrize("keepalive", [True, False])
async def test_progress_frames_carry_their_keepalive_flag(plane, keepalive):
    """A timer-driven frame renews the lease but proves no work was done, so
    the distinction has to survive the boundary."""
    _, attempt = plane.assign()
    seen: list[dict] = []
    plane.scheduler.on_progress = lambda *a, **kw: seen.append(kw)

    await plane.send(
        pb.WorkerMessage(
            progress=pb.TaskProgress(
                ref=codec.ref_for(attempt),
                progress=0.4,
                stage="generating",
                keepalive=keepalive,
            )
        )
    )

    assert seen[0]["keepalive"] is keepalive
    assert seen[0]["stage"] == "generating"
