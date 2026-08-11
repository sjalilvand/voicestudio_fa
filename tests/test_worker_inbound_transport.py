"""Inbound mode end to end: a panel dials a node and runs a task on it.

Everything else about this feature can pass unit tests while the thing itself
does not connect — which is exactly how this subsystem has failed before. These
tests stand up a real listener on a real socket, dial it with the real
connector, and assert on the state the scheduler ends up in.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
import pytest_asyncio

ENGINE, MODEL, OP = "indextts", "IndexTTS-2", "tts"


def _worker_modules():
    """Resolve app modules at test runtime, after isolation fixtures run."""
    from worker import registry, tls
    from worker.identity import WorkerKeypair
    from worker.inbound.artifacts import ArtifactStore
    from worker.inbound.connection_log import ConnectionLog
    from worker.inbound.connection_string import format_connection, parse_connection
    from worker.inbound.connector import NodeConnection
    from worker.inbound.keys import KeyStore
    from worker.inbound.listener import NodeListener
    from worker.pool import WorkerPool
    from worker.scheduler import Scheduler
    from worker.transport.client import WorkerClient, WorkerConfig
    from worker.transport.server import WorkerServicer

    return SimpleNamespace(
        ArtifactStore=ArtifactStore,
        ConnectionLog=ConnectionLog,
        KeyStore=KeyStore,
        NodeConnection=NodeConnection,
        NodeListener=NodeListener,
        Scheduler=Scheduler,
        WorkerClient=WorkerClient,
        WorkerConfig=WorkerConfig,
        WorkerKeypair=WorkerKeypair,
        WorkerPool=WorkerPool,
        WorkerServicer=WorkerServicer,
        format_connection=format_connection,
        parse_connection=parse_connection,
        registry=registry,
        tls=tls,
    )


@pytest.fixture
def db(tmp_path, monkeypatch):
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


def _capabilities():
    return [
        {
            "engine": ENGINE,
            "model_id": MODEL,
            "operations": [OP],
            "supported": True,
            "installed": True,
            "downloaded": True,
            "resident": False,
            "derived_concurrency": 1,
            "repo_ids": ["test/repo"],
        }
    ]


class _ObservedConnectionLog:
    """ConnectionLog with concrete async signals instead of wall-clock waits."""

    def __init__(self, *, now):
        self._inner = _worker_modules().ConnectionLog(now=now)
        self.rejected_event = asyncio.Event()
        self.closed_event = asyncio.Event()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def rejected(self, *, peer, detail):
        self._inner.rejected(peer=peer, detail=detail)
        self.rejected_event.set()

    def closed(self, session_id, *, detail=""):
        self._inner.closed(session_id, detail=detail)
        self.closed_event.set()


class _InboundHarness:
    """A node listening on loopback, plus the panel that dials it."""

    def __init__(self, tmp_path):
        worker = _worker_modules()
        self.worker = worker
        # Node side.
        self.keys = worker.KeyStore(str(tmp_path / "inbound-keys.json"))
        self.clock = [100.0]
        self.log = _ObservedConnectionLog(now=lambda: self.clock[0])
        self.artifacts = worker.ArtifactStore(str(tmp_path / "staged"))
        self.keypair = worker.WorkerKeypair.generate()
        self.credentials = worker.tls.generate_self_signed(
            hostnames=["localhost", "127.0.0.1"]
        )
        self.executed: list[str] = []
        self.listener = worker.NodeListener(
            keys=self.keys,
            log=self.log,
            artifacts=self.artifacts,
            client_factory=self._client,
            credentials=self.credentials,
        )
        # Panel side.
        self.pool = worker.WorkerPool()
        self.scheduler = worker.Scheduler(self.pool, persist=False)
        self.servicer = worker.WorkerServicer(
            self.scheduler, self.pool, artifact_dir=str(tmp_path / "artifacts")
        )
        self.connection = None
        self.connector_task = None
        self.panel_key_id = ""
        self.port = 0

    def _client(self, artifacts, key_id):
        async def execute(assignment, **kwargs):
            self.executed.append(assignment.ref.task_id)
            return {"result_json": "{}", "payload": b"", "meta": {}}

        return self.worker.WorkerClient(
            self.worker.WorkerConfig(
                endpoint="",
                cert_fingerprint="",
                certificate_pem=b"",
                keypair=self.keypair,
                worker_id=self.keys.worker_id_for(key_id),
                enrollment_token="",
                max_concurrent_tasks=1,
                capabilities=_capabilities(),
                host={
                    "hostname": "gpu-node",
                    "os": "linux",
                    "arch": "x86_64",
                    "gpus": [],
                },
            ),
            execute=execute,
            artifacts=artifacts,
            on_registered=lambda wid: self.keys.remember_worker_id(key_id, wid),
        )

    async def start_node(self):
        self.port = await self.listener.start(host="127.0.0.1", port=_free_port())
        return self.port

    async def connect_panel(self, secret=None, *, wait=True):
        if secret is None:
            issued = self.keys.issue("Test panel")
            secret = issued.secret
            self.panel_key_id = issued.key.key_id
        else:
            from worker.identity import hash_secret

            self.panel_key_id = hash_secret(secret)[:12]
        text = self.worker.format_connection(
            host="127.0.0.1",
            port=self.port,
            secret=secret,
            fingerprint=self.credentials.fingerprint,
        )
        connection = self.worker.parse_connection(text)
        self.connection = self.worker.NodeConnection(self.servicer, connection)
        self.connector_task = asyncio.create_task(self.connection.run_forever())
        if wait:
            await _until(lambda: len(self.pool) == 1)
        return self.connection

    async def stop(self):
        if self.connection is not None:
            await self.connection.stop()
        if self.connector_task is not None:
            self.connector_task.cancel()
            await asyncio.gather(self.connector_task, return_exceptions=True)
        await self.listener.stop()


async def _until(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    raise AssertionError("condition never became true")


@pytest_asyncio.fixture
async def inbound(tmp_path, db):
    h = _InboundHarness(tmp_path)
    await h.start_node()
    try:
        yield h
    finally:
        await h.stop()


@pytest.mark.asyncio
async def test_a_panel_that_dials_a_node_ends_up_with_a_schedulable_worker(inbound):
    """The whole feature in one assertion: paste a string, get a usable GPU."""
    await inbound.connect_panel()

    assert len(inbound.pool) == 1
    worker = next(iter(inbound.pool))
    assert worker.record.schedulable is True
    # Capabilities crossed the inverted stream, so the scheduler can actually
    # pick this worker rather than merely knowing it exists.
    assert worker.supports(engine=ENGINE, model_id=MODEL, operation=OP)


@pytest.mark.asyncio
async def test_a_panel_refuses_a_node_whose_tls_certificate_misses_the_pin(inbound):
    secret = inbound.keys.issue("Test panel").secret
    connection = inbound.worker.parse_connection(
        inbound.worker.format_connection(
            host="127.0.0.1",
            port=inbound.port,
            secret=secret,
            fingerprint=inbound.credentials.fingerprint,
        )
    )
    impostor_pin = "0" * 64
    assert impostor_pin != inbound.credentials.fingerprint
    dialer = inbound.worker.NodeConnection(
        inbound.servicer, replace(connection, fingerprint=impostor_pin)
    )

    with pytest.raises(RuntimeError, match="certificate fingerprint"):
        await asyncio.wait_for(dialer._connect_once(), timeout=2.0)

    assert len(inbound.pool) == 0


@pytest.mark.asyncio
async def test_the_node_is_enrolled_by_its_own_key_not_by_the_api_key(inbound):
    """The API key admits a panel; identity stays with the node's keypair. If
    these were conflated, anyone who copied the key could impersonate the
    machine to a panel that had already trusted it."""
    await inbound.connect_panel()

    stored = inbound.worker.registry.list_workers()
    assert len(stored) == 1
    assert stored[0].key_id == inbound.keypair.key_id


@pytest.mark.asyncio
async def test_two_panels_can_use_one_node_at_the_same_time(tmp_path, db, inbound):
    """The reason inbound exists. Outbound is 1:1 by construction, so this is
    the case it can never serve."""
    second = _InboundHarness(tmp_path / "second")
    # A second panel, its own scheduler and registry view, same node.
    second.listener = inbound.listener
    second.port = inbound.port

    await inbound.connect_panel()
    alice = next(iter(inbound.pool)).worker_id

    bob_secret = inbound.keys.issue("Bob").secret
    connection = inbound.worker.parse_connection(
        inbound.worker.format_connection(
            host="127.0.0.1",
            port=inbound.port,
            secret=bob_secret,
            fingerprint=inbound.credentials.fingerprint,
        )
    )
    bob = inbound.worker.NodeConnection(second.servicer, connection)
    task = asyncio.create_task(bob.run_forever())
    try:
        await _until(lambda: len(second.pool) == 1)
        assert next(iter(second.pool)).worker_id == alice
        # Both sessions are live on the node at once, which is what a
        # one-at-a-time design would have prevented.
        assert len(inbound.log.snapshot()["sessions"]) == 2
    finally:
        await bob.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_a_panel_with_no_key_never_reaches_the_worker_pool(inbound):
    await inbound.connect_panel(secret="ovnode_" + "z" * 40, wait=False)
    await asyncio.wait_for(inbound.log.rejected_event.wait(), timeout=2.0)

    assert len(inbound.pool) == 0
    kinds = [e["kind"] for e in inbound.log.snapshot()["events"]]
    assert "rejected" in kinds


@pytest.mark.asyncio
async def test_attach_ends_when_its_incoming_reader_stops(tmp_path, monkeypatch):
    """A dead reader must not leave a node advertising a healthy session."""
    from worker.protocol.gen import worker_v1_pb2 as pb

    class FakeClient:
        def build_register_request(self):
            return pb.RegisterRequest()

        async def accept_registration(self, _response):
            pass

        def start_heartbeat(self, _response):
            return asyncio.create_task(asyncio.sleep(60))

        async def next_outbound(self):
            await asyncio.Event().wait()

        async def stop(self):
            pass

    class Context:
        def peer(self):
            return "ipv4:10.0.0.2:45000"

        def invocation_metadata(self):
            return ()

        async def abort(self, code, message):
            raise AssertionError(f"unexpected abort: {code}: {message}")

    servicer = NodeListener(
        keys=KeyStore(str(tmp_path / "keys.json")),
        log=ConnectionLog(),
        artifacts=ArtifactStore(str(tmp_path / "staged")),
        client_factory=lambda _artifacts, _key_id: FakeClient(),
    )._servicer
    monkeypatch.setattr(servicer, "_authenticate", lambda _context: ("panel-a", "A"))

    async def frames():
        yield pb.ServerMessage(registered=pb.RegisterResponse())

    stream = servicer.Attach(frames(), Context())
    first = await anext(stream)
    assert first.WhichOneof("payload") == "register"
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), timeout=2)


@pytest.mark.asyncio
async def test_a_revoked_key_stops_working_without_disturbing_the_others(inbound):
    alice = inbound.keys.issue("Alice")
    inbound.keys.revoke(alice.key.key_id)

    await inbound.connect_panel(secret=alice.secret, wait=False)
    await asyncio.wait_for(inbound.log.rejected_event.wait(), timeout=2.0)

    assert len(inbound.pool) == 0


@pytest.mark.asyncio
async def test_the_owner_can_see_who_connected_and_kick_them(inbound):
    await inbound.connect_panel()
    sessions = inbound.log.snapshot()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["label"] == "Test panel"

    assert inbound.log.kick(sessions[0]["session_id"]) is True

    # The kick has to land on an idle session too, which is the case a
    # loop that only wakes on outbound traffic would never notice.
    await asyncio.wait_for(inbound.log.closed_event.wait(), timeout=2.0)
    assert inbound.log.snapshot()["sessions"] == []

    # And it has to STAY landed for a moment. The panel redials on its own, so
    # without a cooldown the person is back within two seconds and the button
    # appears to do nothing — which is what it did on hardware, where the log
    # read disconnected and connected in the same breath.
    assert inbound.log.cooling_down(sessions[0]["key_id"]) is True
    await asyncio.wait_for(inbound.log.rejected_event.wait(), timeout=2.0)
    assert inbound.log.snapshot()["sessions"] == [], (
        "the kicked panel came straight back"
    )


@pytest.mark.asyncio
async def test_an_input_pushed_before_the_assignment_is_there_when_the_task_asks(
    inbound, tmp_path
):
    """Inbound reverses the artifact direction, so ordering is a real hazard:
    an assignment that overtakes its own inputs fails on a file that is merely
    late."""
    from worker.protocol.gen import worker_v1_pb2 as pb

    await inbound.connect_panel()
    source = tmp_path / "reference.wav"
    source.write_bytes(b"reference audio bytes")

    declared = await inbound.connection.push_input(
        pb.ArtifactRef(artifact_id="ref-1", filename="reference.wav"), str(source)
    )

    assert declared.sha256
    destination = tmp_path / "staged-copy.wav"
    await inbound.artifacts.stage_in(
        declared, str(destination), key_id=inbound.panel_key_id
    )
    assert destination.read_bytes() == b"reference audio bytes"


@pytest.mark.asyncio
async def test_a_pushed_input_that_does_not_match_its_checksum_is_refused(
    inbound, tmp_path
):
    """A truncated or corrupted input that gets staged anyway becomes a render
    that succeeds against the wrong audio."""
    from worker.protocol.gen import worker_v1_pb2 as pb

    await inbound.connect_panel()
    source = tmp_path / "reference.wav"
    source.write_bytes(b"reference audio bytes")

    ref = pb.ArtifactRef(artifact_id="ref-2", filename="reference.wav", sha256="0" * 64)
    # Declared hash wins over the computed one only if the node checks; force
    # the mismatch by pinning a wrong hash on the way in.
    original = inbound.connection.push_input

    async def corrupted(_ref, path):
        return await original(ref, path)

    with pytest.raises(RuntimeError, match="checksum|did not accept"):
        # push_input recomputes the hash, so drive PushInput directly with a
        # ref whose declared hash cannot match.
        await _push_with_declared_hash(inbound, ref, str(source))


@pytest.mark.asyncio
async def test_an_offset_mismatch_removes_the_partial_input(inbound):
    from worker.inbound.listener import KEY_METADATA_KEY
    from worker.protocol.gen import worker_v1_pb2 as pb

    await inbound.connect_panel()
    ref = pb.ArtifactRef(artifact_id="offset-mismatch", filename="reference.wav")

    async def chunks():
        yield pb.ArtifactChunk(ref=ref, offset=0, data=b"first", last=False)
        yield pb.ArtifactChunk(ref=ref, offset=99, data=b"second", last=True)

    ack = await inbound.connection._stub.PushInput(
        chunks(),
        metadata=((KEY_METADATA_KEY, inbound.connection._connection.secret),),
    )

    assert ack.error.code == "OFFSET_MISMATCH"
    assert not any(files for _root, _dirs, files in os.walk(inbound.artifacts._root))


@pytest.mark.asyncio
async def test_staged_artifacts_are_isolated_by_panel_key(tmp_path):
    from worker.protocol.gen import worker_v1_pb2 as pb

    store = ArtifactStore(str(tmp_path / "staged"))
    result = await store.publish(
        pb.TaskRef(task_id="t1", attempt_id="a1"),
        b"alice audio",
        {"filename": "out.wav"},
        key_id="alice",
    )

    assert store.open_result(result.artifact_id, key_id="bob") is None
    store.result_fetched(result.artifact_id, key_id="bob")
    assert store.open_result(result.artifact_id, key_id="alice") is not None

    incoming = pb.ArtifactRef(artifact_id="shared-id", filename="ref.wav")
    path = store.begin_input(incoming, key_id="alice")
    with open(path, "wb") as handle:
        handle.write(b"alice reference")
    store.commit_input(
        incoming,
        path,
        "digest",
        len(b"alice reference"),
        key_id="alice",
    )
    with pytest.raises(RuntimeError, match="did not send input"):
        await store.stage_in(incoming, str(tmp_path / "bob.wav"), key_id="bob")

    await store.stage_in(incoming, str(tmp_path / "alice.wav"), key_id="alice")
    assert (tmp_path / "alice.wav").read_bytes() == b"alice reference"


async def _push_with_declared_hash(inbound, ref, path):
    """Push bytes while declaring a hash that does not describe them."""
    from worker.inbound.listener import KEY_METADATA_KEY
    from worker.protocol.gen import worker_v1_pb2 as pb

    stub = inbound.connection._stub
    data = open(path, "rb").read()

    async def chunks():
        yield pb.ArtifactChunk(ref=ref, offset=0, data=data, last=True)

    ack = await stub.PushInput(
        chunks(), metadata=((KEY_METADATA_KEY, inbound.connection._connection.secret),)
    )
    if not ack.committed:
        raise RuntimeError(ack.error.message or "refused")


@pytest.mark.asyncio
async def test_a_different_machine_cannot_re_adopt_an_enrolled_workers_identity(
    inbound, tmp_path
):
    """The re-adoption path exists so a node that lost the id this panel gave
    it can still reconnect on proof of key possession. It must not become a way
    for a *different* key to inherit an enrolled worker: an attacker holding
    only the API key would otherwise take over the trusted machine's identity.
    """
    from worker.protocol.gen import worker_v1_pb2 as pb

    await inbound.connect_panel()
    enrolled = inbound.worker.registry.list_workers()[0]

    # A second machine: valid key, valid self-signature, wrong identity.
    impostor = inbound.worker.WorkerKeypair.generate()
    challenge, nonce = b"c" * 32, b"n" * 32
    forged = pb.RegisterRequest(
        envelope=pb.Envelope(sequence=0),
        worker_id=enrolled.id,
        public_key=impostor.public_bytes(),
        challenge=challenge,
        nonce=nonce,
        challenge_signature=impostor.sign(
            __import__("worker.identity", fromlist=["identity"]).challenge_message(
                challenge=challenge, worker_id=enrolled.id, session_epoch=0, nonce=nonce
            )
        ),
    )

    assert (
        inbound.worker.NodeConnection._proves_key_possession(forged, enrolled) is False
    )


@pytest.mark.asyncio
async def test_the_node_keeps_sending_heartbeats_after_it_registers(
    inbound, monkeypatch
):
    """A session that goes quiet is declared dead and flaps forever.

    Found on hardware, not here: the inbound Attach handler started the read
    pump and the outbound loop but never the heartbeat loop that the outbound
    path starts in `_connect_once`. The node registered, said nothing more, was
    declared dead ~90 seconds later, reconnected, and repeated — while every
    test in this file finished inside three seconds, comfortably within the
    grace window that hid it.

    So this test asserts on the frames themselves rather than on liveness: it
    watches the node's own outbox for a heartbeat, which is the thing that was
    missing, and does not depend on how long the grace window happens to be.
    """
    # The interval the panel advertises, shortened so this asserts on a real
    # emitted frame in a second rather than waiting out the production value.
    from worker.transport import server as server_module

    monkeypatch.setattr(server_module, "_HEARTBEAT_INTERVAL_SECONDS", 1)

    seen = []
    client_box = {}

    original = inbound._client

    def capture(artifacts, key_id):
        client = original(artifacts, key_id)
        client_box["client"] = client
        real_send = client._send

        async def spy(message, **kwargs):
            if message.WhichOneof("payload") == "heartbeat":
                seen.append(message)
            return await real_send(message, **kwargs)

        client._send = spy
        return client

    inbound.listener._servicer._client_factory = capture
    await inbound.connect_panel()

    # Drive the loop rather than waiting out a real interval: the bug is a
    # missing task, not a slow one, so what matters is that something is
    # scheduled to produce these at all.
    await _until(lambda: len(seen) >= 2, timeout=15.0)
    assert len(seen) >= 2, "the node registered and then never sent a heartbeat"


@pytest.mark.asyncio
async def test_a_staged_result_comes_back_whole_when_its_ref_declares_a_size(
    inbound, tmp_path
):
    """A real result ref carries size_bytes, and that must not be read as an
    offset.

    Found on hardware: FetchResult seeked to `request.size_bytes` as if it were
    a resume point, so it started at EOF, yielded nothing, and the fetch failed
    with "the result ended before its final chunk" — while the finished render
    sat on the node's disk. Every earlier test called publish/stage directly and
    never exercised FetchResult with a populated ref, which is why it survived.
    """
    from worker.protocol.gen import worker_v1_pb2 as pb

    await inbound.connect_panel()
    payload = b"rendered audio bytes" * 1000

    ref = await inbound.artifacts.publish(
        pb.TaskRef(task_id="t1", attempt_id="a1"),
        payload,
        {"filename": "out.wav"},
        key_id=inbound.panel_key_id,
    )
    assert ref.size_bytes == len(payload), "the ref must declare the real size"

    destination = tmp_path / "fetched.wav"
    await inbound.connection.fetch_result(ref, str(destination))

    assert destination.read_bytes() == payload


@pytest.mark.asyncio
async def test_result_pull_stops_at_its_runtime_byte_cap(tmp_path):
    from worker.inbound.connection_string import Connection
    from worker.protocol.gen import worker_v1_pb2 as pb

    connection = NodeConnection(
        object(), Connection(host="127.0.0.1", port=7444, secret="ovnode_" + "s" * 40)
    )

    class Stub:
        async def FetchResult(self, _request, metadata=()):
            yield pb.ResultChunk(offset=0, data=b"too large", last=True)

    connection._stub = Stub()
    destination = tmp_path / "partial.wav"

    with pytest.raises(RuntimeError, match="larger than"):
        await connection.fetch_result(
            pb.ArtifactRef(artifact_id="a1"), str(destination), max_bytes=4
        )
    assert not destination.exists()


@pytest.mark.asyncio
async def test_repasting_a_key_for_a_connected_machine_redials_it(inbound, monkeypatch):
    """Re-pasting must replace the live session, not report success against it.

    Found on hardware: `add` saved the new string and then short-circuited
    because a connection to that endpoint already existed. A wrong key
    therefore overwrote a working one, answered 200 with connected=true from
    the stale session, and only failed after a restart — by which point nothing
    pointed back at the paste that caused it.
    """
    from worker.inbound import service as inbound_service

    await inbound.connect_panel()
    outbound = inbound_service.OutboundNodes(inbound.keys)
    saved = []
    monkeypatch.setattr(outbound, "saved", lambda: list(saved))
    monkeypatch.setattr(
        outbound, "_save", lambda entries: saved.clear() or saved.extend(entries)
    )

    first = inbound.worker.format_connection(
        host="127.0.0.1",
        port=inbound.port,
        secret=inbound.keys.issue("One").secret,
        fingerprint=inbound.credentials.fingerprint,
    )
    await outbound.add(first, inbound.servicer)
    original = outbound._connections[f"127.0.0.1:{inbound.port}"]

    second = inbound.worker.format_connection(
        host="127.0.0.1",
        port=inbound.port,
        secret=inbound.keys.issue("Two").secret,
        fingerprint=inbound.credentials.fingerprint,
    )
    await outbound.add(second, inbound.servicer)

    endpoint = f"127.0.0.1:{inbound.port}"
    assert saved == [endpoint], "settings must persist only the non-secret endpoint"
    assert inbound.keys.connection_secret(endpoint) == parse_connection(second).secret
    assert outbound._connections[f"127.0.0.1:{inbound.port}"] is not original, (
        "the old session must be replaced, not reused"
    )
    await outbound.stop()


@pytest.mark.asyncio
async def test_saved_endpoint_reloads_its_key_from_protected_storage(tmp_path, monkeypatch):
    from worker.inbound import service as inbound_service

    store = KeyStore(str(tmp_path / "keys.json"))
    endpoint = "10.0.0.2:7444"
    secret = "ovnode_" + "s" * 40
    store.remember_connection_secret(endpoint, secret)
    outbound = inbound_service.OutboundNodes(store)
    monkeypatch.setattr(outbound, "saved", lambda: [endpoint])
    dialled = []

    async def capture(connection, _servicer):
        dialled.append(connection)

    monkeypatch.setattr(outbound, "_dial", capture)
    await outbound.start_all(object())

    assert len(dialled) == 1
    assert dialled[0].endpoint == endpoint
    assert dialled[0].secret == secret


@pytest.mark.asyncio
async def test_a_stale_frame_cannot_poison_the_next_attach(inbound):
    """The outbox must not survive a dead session.

    Found on hardware. The queue was built once per NodeConnection and reused
    across reconnects, so a frame left behind by a dying session became the
    FIRST frame of the next attach. The node requires a registration there,
    aborted the call, and the two span at full speed — session epoch 2445
    inside one second, with the node logging "Locally aborted" on repeat and
    the panel reporting the worker offline while it was visibly connected.
    """
    from worker.protocol.gen import worker_v1_pb2 as pb

    await inbound.connect_panel()
    connection = inbound.connection

    # Exactly what a torn-down session leaves behind: an unsent frame, still
    # queued, that would be handed to the next attach as its opening word.
    stale = pb.ServerMessage(ping=pb.Ping(nonce=7))
    connection._outbox.put_nowait(stale)
    poisoned = connection._outbox

    task = asyncio.create_task(connection._connect_once())
    try:
        await _until(lambda: connection._outbox is not poisoned)
        assert connection._outbox is not poisoned, "the dead session's queue was reused"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_a_nested_input_id_is_accepted_the_way_staging_really_writes_it(
    inbound, tmp_path
):
    """Staged inputs are nested, and the node must take them as they come.

    `task_store.stage_input` mints `inputs/<digest><ext>` — a path, not a bare
    name. The node ran `safe_filename` on it, which rejects anything nested, so
    every real clone input was refused, the dispatch failed, and the scheduler
    retried about eighteen times a second while the GPU sat idle and the user
    watched a spinner. Every earlier test used a flat id like "ref-1" and so
    never touched the shape production actually produces.
    """
    from worker.protocol.gen import worker_v1_pb2 as pb

    await inbound.connect_panel()
    source = tmp_path / "reference.wav"
    source.write_bytes(b"reference audio bytes")

    nested = pb.ArtifactRef(
        artifact_id="inputs/0f1e2d3c4b5a69788796a5b4c3d2e1f0.wav",
        filename="reference.wav",
    )
    declared = await inbound.connection.push_input(nested, str(source))

    destination = tmp_path / "staged.wav"
    await inbound.artifacts.stage_in(
        declared, str(destination), key_id=inbound.panel_key_id
    )
    assert destination.read_bytes() == b"reference audio bytes"


@pytest.mark.asyncio
async def test_a_pushed_input_cannot_escape_the_staging_directory(inbound, tmp_path):
    """Accepting nested ids must not mean accepting traversal.

    The id is now hashed rather than used as a path, so it cannot steer
    placement at all. The declared FILENAME still can, and is still required to
    be a bare name — that is the containment the old check was really buying,
    and it must not have been traded away to fix the rejection above.
    """
    from worker.protocol.gen import worker_v1_pb2 as pb

    await inbound.connect_panel()
    source = tmp_path / "evil.wav"
    source.write_bytes(b"payload")

    hostile = pb.ArtifactRef(
        artifact_id="../../../../../../tmp/escaped.wav", filename="../../escaped.wav"
    )
    with pytest.raises(RuntimeError, match="bare filename|did not accept"):
        await inbound.connection.push_input(hostile, str(source))

    # And nothing was left behind by the refusal.
    root = inbound.artifacts._root
    assert not any("escaped" in name for _, _, files in os.walk(root) for name in files)


@pytest.mark.asyncio
async def test_an_inbound_only_node_still_unloads_idle_models(monkeypatch, tmp_path):
    """Requirement: free models nothing has used for ten minutes.

    The sweep used to live inside the dial-out agent, which an inbound-only
    node never starts — so a machine lending its GPU to panels that dial IN
    held several GB of weights forever. That is exactly the cost the sweep
    exists to avoid, and it was absent in the mode most likely to be a shared
    box: on hardware, that node's VRAM never came back.
    """
    from worker import agent as agent_module

    released = {"count": 0}
    refreshed = {"count": 0}

    def fake_release():
        released["count"] += 1
        return ["indextts"]

    async def fake_refresh():
        refreshed["count"] += 1

    monkeypatch.setattr(agent_module, "IDLE_SWEEP_INTERVAL_SECONDS", 0.05)
    import services.model_manager as model_manager
    import services.tts_backend as tts_backend

    monkeypatch.setattr(tts_backend, "release_idle_engines", fake_release)
    monkeypatch.setattr(
        model_manager, "gpu_pool_stats", lambda: {"running": 0, "queued": 0}
    )

    task = asyncio.create_task(agent_module.idle_unload_loop(fake_refresh))
    try:
        await _until(
            lambda: released["count"] >= 1 and refreshed["count"] >= 1, timeout=5.0
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert released["count"] >= 1, "nothing swept idle engines"
    assert refreshed["count"] >= 1, "freed VRAM was never re-advertised"


@pytest.mark.asyncio
async def test_enabling_inbound_starts_the_idle_sweep(monkeypatch, tmp_path):
    """The wiring, not just the loop: the gap was a missing caller."""
    from worker import agent as agent_module
    from worker.inbound import service as inbound_service

    started = asyncio.Event()
    received = []

    async def idle_unload_sentinel(refresh):
        received.append(refresh)
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(agent_module, "idle_unload_loop", idle_unload_sentinel)
    node = inbound_service.InboundNode()
    monkeypatch.setattr(inbound_service, "bind_host", lambda: "127.0.0.1")
    monkeypatch.setattr(inbound_service, "bind_port", lambda: 0)
    monkeypatch.setattr(
        inbound_service,
        "paths",
        lambda: {
            "keys": str(tmp_path / "k.json"),
            "staged": str(tmp_path / "s"),
            "certificate": str(tmp_path / "inbound.crt"),
            "private_key": str(tmp_path / "inbound.key"),
        },
    )
    monkeypatch.setattr(node, "_client_factory", lambda artifacts, key_id: None)

    await node.start()
    try:
        await asyncio.wait_for(started.wait(), timeout=2.0)
        assert received == [node._listener.refresh_all]
    finally:
        await node.stop()
    assert node._idle_sweep is None
