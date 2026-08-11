"""Worker-side liveness and result-size guards.

Two failures these cover were invisible to every existing test because both
live in the gap between "the client sent something" and "the client kept
sending something":

* **B1** — the client never emitted a single progress frame, so the control
  plane's 120 s progress lease expired on any task that ran longer than that,
  starting with the cold model load that happens *after* TaskStarted.
* **B9** — a result too large for one gRPC frame was recorded for redelivery
  before it was sent, so it was re-sent on every reconnect, tore the session
  down every time, and blocked every other task on that worker forever.

These drive a real ``WorkerClient`` and read its outbox rather than standing up
a server: the invariant being asserted is what this side puts on the wire and
when, which a server round trip would only obscure.
"""
from __future__ import annotations

import asyncio

import pytest

from worker.errors import ErrorClass
from worker.identity import WorkerKeypair
from worker.protocol.gen import worker_v1_pb2 as pb
from worker.transport.client import (
    MAX_MESSAGE_BYTES,
    WorkerClient,
    WorkerConfig,
    keepalive_interval,
)

ENGINE, MODEL, OP = "indextts", "indextts:v2", "tts"

# The protocol carries the lease as uint32 seconds, so one second is the
# shortest lease a real assignment can express — and the test task then runs
# for three of them.
LEASE_SECONDS = 1


def _client(execute, *, max_concurrent_tasks: int = 1) -> WorkerClient:
    """A client that is never connected; only its outbox is read."""
    config = WorkerConfig(
        endpoint="127.0.0.1:1",
        cert_fingerprint="",
        certificate_pem=b"",
        keypair=WorkerKeypair.generate(),
        worker_id="w-1",
        max_concurrent_tasks=max_concurrent_tasks,
    )
    return WorkerClient(config, execute=execute)


def _assignment(*, lease_seconds: int = LEASE_SECONDS) -> pb.TaskAssignment:
    return pb.TaskAssignment(
        ref=pb.TaskRef(task_id="t-1", attempt_id="a-1", session_epoch=1),
        operation=OP,
        engine=ENGINE,
        model_id=MODEL,
        params_json="{}",
        deadlines=pb.Deadlines(
            accept_seconds=20,
            model_load_seconds=600,
            execution_seconds=300,
            progress_lease_seconds=lease_seconds,
        ),
    )


class _Wire:
    """Drains the client's outbox, recording each frame's arrival time."""

    def __init__(self, client: WorkerClient) -> None:
        self.frames: list[tuple[float, pb.WorkerMessage]] = []
        self._task = asyncio.create_task(self._drain(client))

    async def _drain(self, client: WorkerClient) -> None:
        loop = asyncio.get_running_loop()
        while True:
            message = await client._outbox.get()
            self.frames.append((loop.time(), message))

    def kinds(self) -> list[str]:
        return [m.WhichOneof("payload") for _, m in self.frames]

    def of(self, kind: str) -> list[pb.WorkerMessage]:
        return [m for _, m in self.frames if m.WhichOneof("payload") == kind]

    async def until(self, *kinds: str, timeout: float = 10.0) -> pb.WorkerMessage:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            for _, message in self.frames:
                if message.WhichOneof("payload") in kinds:
                    return message
            await asyncio.sleep(0.02)
        raise AssertionError(f"no {kinds} frame; saw {self.kinds()}")

    async def close(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


async def _settle(client: WorkerClient, timeout: float = 10.0) -> None:
    """Wait for the running task to leave the client's book."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if not client._running:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the task never finished")


# ── B1: the progress lease is renewed ──────────────────────────────────────


def test_keepalive_interval_is_a_third_of_the_lease():
    assert keepalive_interval(120) == 40.0


def test_a_missing_lease_falls_back_rather_than_spinning():
    """An older control plane sends no deadlines at all; 0/3 would busy-loop."""
    assert keepalive_interval(0) == 40.0
    assert keepalive_interval(-5) == 40.0


@pytest.mark.asyncio
async def test_keepalive_renews_a_lease_across_a_task_three_leases_long():
    """The B1 regression: silence longer than one lease kills the attempt.

    Asserted as a gap invariant rather than a frame count, because the lease
    expires on the *interval between* frames — a hundred frames in the first
    second and nothing after would still lose the task.
    """
    started = asyncio.Event()

    async def execute(assignment, **_):
        started.set()
        await asyncio.sleep(LEASE_SECONDS * 3)
        return {"meta": {"ok": True}, "payload": b"audio"}

    client = _client(execute)
    wire = _Wire(client)
    try:
        await client._on_assignment(_assignment())
        await asyncio.wait_for(started.wait(), timeout=5)
        await wire.until("result", timeout=LEASE_SECONDS * 6)

        times = [t for t, _ in wire.frames]
        gaps = [b - a for a, b in zip(times, times[1:])]
        assert max(gaps) < LEASE_SECONDS, (
            f"went silent for {max(gaps):.2f}s under a {LEASE_SECONDS}s lease"
        )

        keepalives = [m.progress for m in wire.of("progress") if m.progress.keepalive]
        assert keepalives, "no keepalive frames at all"
        # A lease renewal must not claim work that did not happen.
        assert all(k.progress == 0.0 and not k.stage for k in keepalives)
    finally:
        await wire.close()


@pytest.mark.asyncio
async def test_keepalive_stops_when_the_task_completes():
    """A timer outliving its task renews the lease of an attempt the server
    has already settled — and keeps one alive for a worker that has crashed."""

    async def execute(assignment, **_):
        return {"meta": {"ok": True}, "payload": b"audio"}

    client = _client(execute)
    wire = _Wire(client)
    try:
        await client._on_assignment(_assignment())
        await wire.until("result")
        await _settle(client)
        assert client._keepalives == {}

        before = len(wire.frames)
        await asyncio.sleep(keepalive_interval(LEASE_SECONDS) * 2.5)
        assert len(wire.frames) == before, f"frames kept arriving: {wire.kinds()}"
    finally:
        await wire.close()


@pytest.mark.asyncio
async def test_keepalive_stops_when_the_task_fails():
    async def execute(assignment, **_):
        raise RuntimeError("engine exploded")

    client = _client(execute)
    wire = _Wire(client)
    try:
        await client._on_assignment(_assignment())
        await wire.until("failed")
        await _settle(client)
        assert client._keepalives == {}
    finally:
        await wire.close()


@pytest.mark.asyncio
async def test_keepalive_stops_when_the_server_disowns_the_task():
    """_abandon must silence the timer immediately: cancelling the task does
    not run its finally until the loop next schedules it."""
    entered = asyncio.Event()

    async def execute(assignment, **_):
        entered.set()
        await asyncio.sleep(60)
        return {"meta": {}, "payload": b""}

    client = _client(execute)
    wire = _Wire(client)
    try:
        assignment = _assignment()
        await client._on_assignment(assignment)
        await asyncio.wait_for(entered.wait(), timeout=5)
        await client._abandon("t-1/a-1")
        assert client._keepalives == {}
    finally:
        await wire.close()


@pytest.mark.asyncio
async def test_real_progress_is_forwarded_and_not_marked_keepalive():
    """Keepalive and real progress must stay distinguishable on the wire, or
    the server cannot bound one and trust the other."""

    async def execute(assignment, *, on_progress=None, on_model_loading=None):
        await on_model_loading(0.0, "preparing")
        await on_progress(0.5, "synthesising")
        return {"meta": {"ok": True}, "payload": b"audio"}

    client = _client(execute)
    wire = _Wire(client)
    try:
        await client._on_assignment(_assignment())
        await wire.until("result")

        loading = wire.of("model_loading")
        assert [m.model_loading.engine for m in loading] == [ENGINE]
        assert loading[0].model_loading.detail == "preparing"

        real = [m.progress for m in wire.of("progress") if not m.progress.keepalive]
        assert [(p.progress, p.stage) for p in real] == [(0.5, "synthesising")]
    finally:
        await wire.close()


@pytest.mark.asyncio
async def test_an_executor_that_takes_no_reporters_still_runs():
    """The reporter keywords are probed, not assumed — otherwise injecting a
    plain ``async def (assignment)`` reports a TypeError as a failed job."""

    async def execute(assignment):
        return {"meta": {"ok": True}, "payload": b"audio"}

    client = _client(execute)
    wire = _Wire(client)
    try:
        await client._on_assignment(_assignment())
        message = await wire.until("result", "failed")
        assert message.WhichOneof("payload") == "result"
    finally:
        await wire.close()


# ── B9: an over-cap result is a failure, never a redelivery ────────────────


@pytest.mark.asyncio
async def test_an_oversized_result_never_enters_the_redelivery_set():
    """The B9 regression: recorded-then-rejected means it is re-sent on every
    reconnect, killing the session each time and stranding every other task."""
    oversized = b"\0" * (MAX_MESSAGE_BYTES + 1024)

    async def execute(assignment, **_):
        return {"meta": {"bytes": len(oversized), "inline": False}, "payload": oversized}

    client = _client(execute)
    wire = _Wire(client)
    try:
        await client._on_assignment(_assignment())
        failed = await wire.until("failed")
        await _settle(client)

        assert client._pending == {}
        assert "result" not in wire.kinds()
        assert failed.failed.error.code == "RESULT_TOO_LARGE"
        # TERMINAL: the size is a property of the output, so every worker in
        # the fleet would produce the same frame and be rejected the same way.
        assert failed.failed.error.error_class == pb.ERROR_CLASS_TERMINAL

        before = len(wire.frames)
        await client._redeliver_pending()
        await asyncio.sleep(0.05)
        assert len(wire.frames) == before
    finally:
        await wire.close()


@pytest.mark.asyncio
async def test_a_result_that_fits_is_still_held_for_redelivery():
    """The guard must not cost at-least-once delivery for ordinary results."""

    async def execute(assignment, **_):
        return {"meta": {"ok": True}, "payload": b"\0" * 1024}

    client = _client(execute)
    wire = _Wire(client)
    try:
        await client._on_assignment(_assignment())
        await wire.until("result")
        await _settle(client)
        assert list(client._pending) == ["t-1/a-1"]

        await client._redeliver_pending()
        await asyncio.sleep(0.05)
        assert wire.kinds().count("result") == 2
    finally:
        await wire.close()


@pytest.mark.asyncio
async def test_the_size_gate_measures_the_frame_not_just_the_payload():
    """A modest waveform under a huge result_json overflows the same frame —
    a payload-only check would let that one through and back into _pending."""

    async def execute(assignment, **_):
        return {
            "meta": {"transcript": "x" * (MAX_MESSAGE_BYTES + 1024)},
            "payload": b"\0" * 1024,
        }

    client = _client(execute)
    wire = _Wire(client)
    try:
        await client._on_assignment(_assignment())
        failed = await wire.until("failed")
        await _settle(client)
        assert client._pending == {}
        assert failed.failed.error.code == "RESULT_TOO_LARGE"
    finally:
        await wire.close()


def test_result_too_large_is_terminal_in_the_taxonomy():
    """Guards the codec mapping the wire assertion above depends on."""
    from worker.transport import codec

    error = codec.error_from_pb(
        pb.Error(error_class=pb.ERROR_CLASS_TERMINAL, code="RESULT_TOO_LARGE", message="x")
    )
    assert error.error_class is ErrorClass.TERMINAL
    assert error.retryable is False
