"""Transport: TLS, codec, and a real end-to-end gRPC round trip.

The end-to-end test starts an actual TLS server on a loopback port and drives a
real worker client through it. Mocking the transport would prove only that the
mocks agree with each other; the wiring between protobuf, the servicer, and the
scheduler is exactly what this layer exists to get right.
"""
from __future__ import annotations

import asyncio
import socket
import sqlite3

import pytest
import pytest_asyncio

from worker import identity, registry, tls
from worker.errors import ErrorClass, WorkerError
from worker.identity import WorkerKeypair
from worker.lifecycle import TaskState
from worker.pool import WorkerPool
from worker.protocol.gen import worker_v1_pb2 as pb
from worker.scheduler import Scheduler
import grpc

from worker.protocol.gen import worker_v1_pb2_grpc as pb_grpc
from worker.transport import codec
from worker.transport.client import WorkerClient, WorkerConfig, backoff_delay, config_from_token
from worker.transport.server import WorkerServicer, serve

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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _capabilities(resident: bool = False) -> list[dict]:
    return [
        {
            "engine": ENGINE,
            "model_id": MODEL,
            "operations": [OP],
            "supported": True,
            "installed": True,
            "downloaded": True,
            "resident": resident,
            "backend": "cuda",
            "free_memory_bytes": 24 * 1024**3,
        }
    ]


# ── TLS ────────────────────────────────────────────────────────────────────


def test_self_signed_certificate_is_generated_and_pinnable():
    creds = tls.generate_self_signed(hostnames=["localhost", "127.0.0.1"])
    assert creds.certificate_pem.startswith(b"-----BEGIN CERTIFICATE-----")
    assert tls.pin_matches(creds.certificate_der, creds.fingerprint) is True


def test_a_different_certificate_fails_the_pin():
    """The café-network substitution this whole design exists to stop."""
    mine = tls.generate_self_signed(hostnames=["localhost"])
    attacker = tls.generate_self_signed(hostnames=["localhost"])
    assert tls.pin_matches(attacker.certificate_der, mine.fingerprint) is False


def test_certificate_is_persisted_and_reused(tmp_path):
    cert, key = str(tmp_path / "c.pem"), str(tmp_path / "k.pem")
    first = tls.load_or_create(cert, key, hostnames=["localhost"])
    second = tls.load_or_create(cert, key, hostnames=["localhost"])
    assert first.fingerprint == second.fingerprint


def test_hostname_suffix_is_not_doubled(monkeypatch):
    """macOS already reports the hostname with .local, and 'host.local.local'
    is in nobody's certificate."""
    monkeypatch.setattr(socket, "gethostname", lambda: "mac.local")
    assert "mac.local.local" not in tls.default_hostnames()


def test_private_key_is_not_world_readable(tmp_path):
    import os
    import stat
    import sys

    cert, key = str(tmp_path / "c.pem"), str(tmp_path / "k.pem")
    tls.load_or_create(cert, key, hostnames=["localhost"])
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(key).st_mode) == 0o600


def test_token_with_a_mismatched_certificate_is_refused():
    """config_from_token must refuse rather than offer an override."""
    server = tls.generate_self_signed(hostnames=["localhost"])
    attacker = tls.generate_self_signed(hostnames=["localhost"])
    token = identity.mint_enrollment_token(
        endpoint="localhost:1", cert_fingerprint=server.fingerprint
    )
    with pytest.raises(ValueError, match="does not match"):
        config_from_token(
            token.encode(),
            keypair=WorkerKeypair.generate(),
            certificate_pem=attacker.certificate_pem,
        )


def test_expired_token_is_refused():
    server = tls.generate_self_signed(hostnames=["localhost"])
    token = identity.mint_enrollment_token(
        endpoint="localhost:1", cert_fingerprint=server.fingerprint, ttl_seconds=-1
    )
    with pytest.raises(ValueError, match="expired"):
        config_from_token(
            token.encode(),
            keypair=WorkerKeypair.generate(),
            certificate_pem=server.certificate_pem,
        )


# ── Codec ──────────────────────────────────────────────────────────────────


def test_error_round_trips_through_protobuf():
    original = WorkerError(
        error_class=ErrorClass.CAPABILITY, code="INSUFFICIENT_MEMORY", message="too big", hint="h"
    )
    restored = codec.error_from_pb(codec.error_to_pb(original))
    assert restored == original


def test_unknown_error_class_degrades_to_retryable():
    """A newer peer describing a failure we do not know must not permanently
    fail work that would have succeeded on retry."""
    restored = codec.error_from_pb(pb.Error(code="FROM_THE_FUTURE", message="?"))
    assert restored.error_class is ErrorClass.TRANSIENT
    assert restored.retryable is True


def test_capability_concurrency_is_derived_when_not_supplied():
    """Never defaulted to a constant: a wrong value corrupts output (#315)."""
    message = codec.capability_to_pb(
        {"engine": ENGINE, "model_id": MODEL, "backend": "cuda", "free_memory_bytes": 24 * 1024**3}
    )
    assert message.derived_concurrency >= 1


def test_apple_capability_stays_serial():
    message = codec.capability_to_pb(
        {"engine": ENGINE, "model_id": MODEL, "backend": "mps", "free_memory_bytes": 64 * 1024**3}
    )
    assert message.derived_concurrency == 1


def test_capability_round_trips():
    original = _capabilities(resident=True)[0]
    restored = codec.capability_from_pb(codec.capability_to_pb(original))
    assert restored["engine"] == original["engine"]
    assert restored["resident"] is True
    assert restored["installed"] is True


def test_host_round_trips():
    host = {
        "hostname": "box",
        "os": "linux",
        "arch": "x86_64",
        "worker_version": "0.3.1",
        "cpu_count": 16,
        "gpus": [{"vendor": "nvidia", "model": "RTX 4090", "backend": "cuda", "memory_bytes": 1}],
    }
    restored = codec.host_from_pb(codec.host_to_pb(host))
    assert restored["hostname"] == "box"
    assert restored["gpus"][0]["model"] == "RTX 4090"


# ── Backoff ────────────────────────────────────────────────────────────────


def test_backoff_grows_and_is_bounded():
    assert backoff_delay(1, jitter=lambda: 1.0) == 1.0
    assert backoff_delay(4, jitter=lambda: 1.0) == 8.0
    assert backoff_delay(50, jitter=lambda: 1.0) == 60.0


def test_backoff_is_jittered():
    """Deterministic delays reconnect every worker behind one router in the
    same instant — a spike exactly when the server can least absorb it."""
    assert backoff_delay(5, jitter=lambda: 0.0) == 0.0
    assert backoff_delay(5, jitter=lambda: 0.5) == 8.0


# ── End to end ─────────────────────────────────────────────────────────────


class _Harness:
    """A live TLS server plus a connected worker client."""

    def __init__(self, tmp_path):
        self.pool = WorkerPool()
        self.scheduler = Scheduler(self.pool, persist=True)
        self.creds = tls.generate_self_signed(hostnames=["localhost", "127.0.0.1"])
        self.servicer = WorkerServicer(
            self.scheduler,
            self.pool,
            artifact_dir=str(tmp_path / "artifacts"),
            cert_fingerprint=self.creds.fingerprint,
        )
        self.port = _free_port()
        self.server = None
        self.client = None
        self.client_task = None
        self.executed: list[str] = []

    async def start(self):
        self.server = await serve(
            self.servicer,
            host="127.0.0.1",
            port=self.port,
            certificate_pem=self.creds.certificate_pem,
            private_key_pem=self.creds.private_key_pem,
        )

    async def connect_worker(self, *, execute=None, capabilities=None):
        token = registry.create_enrollment(
            endpoint=f"localhost:{self.port}", cert_fingerprint=self.creds.fingerprint
        )
        config = WorkerConfig(
            endpoint=f"localhost:{self.port}",
            cert_fingerprint=self.creds.fingerprint,
            certificate_pem=self.creds.certificate_pem,
            keypair=WorkerKeypair.generate(),
            enrollment_token=token.encode(),
            max_concurrent_tasks=2,
            capabilities=capabilities or _capabilities(),
            host={"hostname": "test-worker", "os": "linux", "arch": "x86_64"},
        )

        async def _default_execute(assignment):
            self.executed.append(assignment.ref.task_id)
            return {"meta": {"ok": True}, "payload": b"audio-bytes"}

        self.client = WorkerClient(config, execute=execute or _default_execute)
        self.client_task = asyncio.create_task(self.client.run_forever())
        await self._await_connection()
        return self.client

    async def _await_connection(self, timeout=10.0):
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if len(self.pool) and self.servicer._sessions:
                return
            await asyncio.sleep(0.05)
        raise AssertionError("worker never connected")

    async def await_state(self, task_id, state, timeout=15.0):
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            task = self.scheduler.get(task_id)
            if task is not None and task.state is state:
                return task
            await asyncio.sleep(0.05)
        actual = self.scheduler.get(task_id)
        raise AssertionError(
            f"task never reached {state}; last state {actual.state if actual else None}"
        )

    async def stop(self):
        if self.client is not None:
            await self.client.stop()
        if self.client_task is not None:
            self.client_task.cancel()
            await asyncio.gather(self.client_task, return_exceptions=True)
        if self.server is not None:
            await self.server.stop(grace=0)


@pytest_asyncio.fixture
async def harness(tmp_path, db):
    h = _Harness(tmp_path)
    await h.start()
    try:
        yield h
    finally:
        await h.stop()


@pytest.mark.asyncio
async def test_worker_enrolls_over_tls(harness):
    """The full join: token → TLS → keypair identity → registered worker."""
    await harness.connect_worker()

    assert len(harness.pool) == 1
    stored = registry.list_workers()
    assert len(stored) == 1
    assert stored[0].name == "test-worker"
    assert stored[0].schedulable is True


@pytest.mark.asyncio
async def test_enrollment_token_is_single_use(harness, db):
    """A second worker cannot join on a token that has been spent."""
    await harness.connect_worker()
    token = identity.EnrollmentToken.decode(
        registry.create_enrollment(
            endpoint=f"localhost:{harness.port}", cert_fingerprint=harness.creds.fingerprint
        ).encode()
    )
    assert registry.redeem_enrollment(token, worker_id="a") is True
    assert registry.redeem_enrollment(token, worker_id="b") is False


@pytest.mark.asyncio
async def test_task_flows_end_to_end(harness):
    """Submit → dispatch → execute on the worker → result committed."""
    await harness.connect_worker()

    task = harness.scheduler.submit(operation=OP, engine=ENGINE, model_id=MODEL)
    assignment = harness.scheduler.next_assignment()
    assert assignment is not None
    assert await harness.servicer.dispatch(assignment) is True

    completed = await harness.await_state(task.task_id, TaskState.COMPLETED)

    assert harness.executed == [task.task_id]
    assert completed.result_ref is not None


@pytest.mark.asyncio
async def test_result_is_persisted_before_it_is_acknowledged(harness):
    """The ordering that makes at-least-once safe: if the ack arrived first and
    the server then died, a finished render would be gone."""
    from worker import task_store

    await harness.connect_worker()
    task = harness.scheduler.submit(operation=OP, engine=ENGINE, model_id=MODEL)
    await harness.servicer.dispatch(harness.scheduler.next_assignment())
    await harness.await_state(task.task_id, TaskState.COMPLETED)

    assert task_store.is_committed(task.task_id) is True


@pytest.mark.asyncio
async def test_worker_failure_propagates_with_its_taxonomy(harness):
    async def _boom(assignment):
        raise RuntimeError("the engine exploded")

    await harness.connect_worker(execute=_boom)
    task = harness.scheduler.submit(
        operation=OP, engine=ENGINE, model_id=MODEL, max_attempts=1
    )
    await harness.servicer.dispatch(harness.scheduler.next_assignment())

    failed = await harness.await_state(task.task_id, TaskState.FAILED)
    assert failed.error is not None
    assert "exploded" in failed.attempts[-1].error.message


@pytest.mark.asyncio
async def test_worker_at_capacity_rejects_without_penalty(harness):
    """The worker's own accept/reject is authoritative; the scheduler's view of
    capacity is only ever advisory."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def _block(assignment):
        started.set()
        await release.wait()
        return {"meta": {}, "payload": b""}

    await harness.connect_worker(execute=_block)
    harness.client.config.max_concurrent_tasks = 1

    first = harness.scheduler.submit(operation=OP, engine=ENGINE, model_id=MODEL)
    await harness.servicer.dispatch(harness.scheduler.next_assignment())
    await asyncio.wait_for(started.wait(), timeout=10)

    # Force a second assignment onto a worker the scheduler thinks has room.
    second = harness.scheduler.submit(operation=OP, engine=ENGINE, model_id=MODEL)
    assignment = harness.scheduler.next_assignment()
    if assignment is not None:
        await harness.servicer.dispatch(assignment)
        await asyncio.sleep(0.5)
        assert second.state in (TaskState.QUEUED, TaskState.ASSIGNED, TaskState.ACCEPTED)
        assert second.excluded_workers == set()

    release.set()
    await harness.await_state(first.task_id, TaskState.COMPLETED)


@pytest.mark.asyncio
async def test_stale_epoch_messages_are_ignored(harness):
    """A half-open previous stream must not be able to drive a live task."""
    await harness.connect_worker()
    task = harness.scheduler.submit(operation=OP, engine=ENGINE, model_id=MODEL)
    assignment = harness.scheduler.next_assignment()

    ignored = harness.scheduler.on_accepted(
        task.task_id, assignment.attempt.attempt_id, epoch=assignment.attempt.session_epoch + 5
    )
    assert ignored is None
    assert task.state is TaskState.ASSIGNED


@pytest.mark.asyncio
async def test_disconnect_starts_a_grace_window_rather_than_failing(harness):
    await harness.connect_worker()
    task = harness.scheduler.submit(operation=OP, engine=ENGINE, model_id=MODEL)
    assignment = harness.scheduler.next_assignment()
    harness.scheduler.on_accepted(
        task.task_id, assignment.attempt.attempt_id, epoch=assignment.attempt.session_epoch
    )
    harness.scheduler.on_started(
        task.task_id, assignment.attempt.attempt_id, epoch=assignment.attempt.session_epoch
    )

    harness.scheduler.on_disconnected(assignment.worker.worker_id)

    assert task.state is TaskState.RUNNING
    assert assignment.attempt.grace_expires_at is not None


@pytest.mark.asyncio
async def test_control_stream_requires_a_session(harness):
    """An unauthenticated stream must be refused, not merely ignored."""
    import grpc

    from worker.protocol.gen import worker_v1_pb2_grpc as pb_grpc

    credentials = grpc.ssl_channel_credentials(root_certificates=harness.creds.certificate_pem)
    async with grpc.aio.secure_channel(f"localhost:{harness.port}", credentials) as channel:
        stub = pb_grpc.WorkerServiceStub(channel)

        async def _messages():
            yield pb.WorkerMessage(heartbeat=pb.Heartbeat(active_tasks=0, available_slots=1))

        with pytest.raises(grpc.aio.AioRpcError) as exc:
            async for _ in stub.Control(_messages()):
                pass
        assert exc.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_registration_refuses_an_unknown_key(harness, db):
    """Knowing a worker id proves nothing without the private key."""
    import grpc

    from worker.protocol.gen import worker_v1_pb2_grpc as pb_grpc

    credentials = grpc.ssl_channel_credentials(root_certificates=harness.creds.certificate_pem)
    async with grpc.aio.secure_channel(f"localhost:{harness.port}", credentials) as channel:
        stub = pb_grpc.WorkerServiceStub(channel)
        stranger = WorkerKeypair.generate()
        response = await stub.Register(
            pb.RegisterRequest(
                protocol_version_min=1,
                protocol_version_max=1,
                public_key=stranger.public_bytes(),
                challenge=b"c" * 32,
                challenge_signature=b"x" * 64,
                nonce=b"n" * 32,
            )
        )
    assert response.error.code == "AUTH_FAILED"
    assert not response.session_token


@pytest.mark.asyncio
async def test_registration_refuses_an_incompatible_protocol(harness, db):
    import grpc

    from worker.protocol.gen import worker_v1_pb2_grpc as pb_grpc

    credentials = grpc.ssl_channel_credentials(root_certificates=harness.creds.certificate_pem)
    async with grpc.aio.secure_channel(f"localhost:{harness.port}", credentials) as channel:
        stub = pb_grpc.WorkerServiceStub(channel)
        response = await stub.Register(
            pb.RegisterRequest(protocol_version_min=99, protocol_version_max=99)
        )
    assert response.error.code == "UPGRADE_REQUIRED"
    assert "update" in response.error.message.lower()


@pytest.mark.asyncio
async def test_artifact_download_cannot_escape_its_directory(harness):
    """An artifact id is attacker-controlled input from a remote peer."""
    assert harness.servicer._resolve_input("../../../../etc/passwd") is None
    assert harness.servicer._resolve_input("") is None


def test_default_hostnames_include_a_routable_address():
    """gRPC resolves through c-ares, which does not speak mDNS. A certificate
    that only names `host.local` produces a token no worker can connect with —
    found by actually running the thing, not by a unit test."""
    names = tls.default_hostnames()
    assert "localhost" in names
    address = tls.primary_ip()
    if address:
        assert address in names


def test_certificate_regenerates_when_it_stops_covering_this_machine(tmp_path, monkeypatch):
    """A laptop that moved networks otherwise keeps a certificate no worker on
    the new network can validate."""
    cert, key = str(tmp_path / "c.pem"), str(tmp_path / "k.pem")
    monkeypatch.setattr(tls, "primary_ip", lambda: "10.0.0.5")
    first = tls.load_or_create(cert, key)
    assert tls.covers(first, "10.0.0.5")

    monkeypatch.setattr(tls, "primary_ip", lambda: "192.168.9.9")
    second = tls.load_or_create(cert, key)

    assert second.fingerprint != first.fingerprint
    assert tls.covers(second, "192.168.9.9")


def test_explicit_hostnames_are_not_second_guessed(tmp_path, monkeypatch):
    monkeypatch.setattr(tls, "primary_ip", lambda: "10.0.0.5")
    cert, key = str(tmp_path / "c.pem"), str(tmp_path / "k.pem")
    first = tls.load_or_create(cert, key, hostnames=["localhost"])
    second = tls.load_or_create(cert, key, hostnames=["localhost"])
    assert first.fingerprint == second.fingerprint


@pytest.mark.asyncio
async def test_a_restarted_worker_reconnects_without_a_new_token(harness, tmp_path):
    """Key-based identity is pointless if a restart needs a fresh token.

    The challenge signature binds to the worker id, so a worker that does not
    remember its own id signs something the server cannot verify — and every
    reconnect fails AUTH_FAILED. Found by restarting a real worker, not by a
    unit test: every earlier test enrolled fresh with a token.
    """
    from worker import agent as worker_agent

    root = tmp_path / "worker-state"
    root.mkdir()
    monkey_paths = {
        "root": str(root),
        "worker_key": str(root / "worker.key"),
        "pinned_cert": str(root / "pinned.crt"),
        "worker_id": str(root / "worker-id"),
    }
    original_paths = worker_agent._paths
    worker_agent._paths = lambda: monkey_paths
    try:
        # First run: enroll with a token, exactly as a new machine would.
        token = registry.create_enrollment(
            endpoint=f"127.0.0.1:{harness.port}", cert_fingerprint=harness.creds.fingerprint
        )
        agent = worker_agent.WorkerAgent()
        await agent.start(token_text=token.encode())
        await harness._await_connection()
        first_id = registry.list_workers()[0].id
        assert worker_agent.load_worker_id(monkey_paths["worker_id"]) == first_id

        # The process goes away.
        await agent.stop()
        harness.pool.disconnect(first_id)
        harness.servicer._sessions.clear()
        harness.servicer._by_token.clear()

        # Second run: no token, only the key and the remembered id.
        revived = worker_agent.WorkerAgent()
        await revived.start(endpoint=f"127.0.0.1:{harness.port}")
        await harness._await_connection()

        assert len(registry.list_workers()) == 1, "a reconnect must not enroll a second worker"
        assert harness.pool.get(first_id) is not None
        await revived.stop()
    finally:
        worker_agent._paths = original_paths



@pytest.mark.asyncio
async def test_server_accepts_the_keepalive_interval_it_configures(monkeypatch):
    """The server must not evict healthy idle workers for its own ping policy."""
    captured = {}

    class FakeServer:
        def add_secure_port(self, *_args):
            return 7443

        async def start(self):
            pass

    def fake_server(*, options):
        captured.update(dict(options))
        return FakeServer()

    monkeypatch.setattr(grpc.aio, "server", fake_server)
    monkeypatch.setattr(pb_grpc, "add_WorkerServiceServicer_to_server", lambda *_args: None)
    monkeypatch.setattr(grpc, "ssl_server_credentials", lambda *_args: object())

    await serve(
        object(),
        certificate_pem=b"certificate",
        private_key_pem=b"private-key",
    )

    assert captured["grpc.http2.min_ping_interval_without_data_ms"] <= 25_000
    assert captured["grpc.http2.max_pings_without_data"] == 0
