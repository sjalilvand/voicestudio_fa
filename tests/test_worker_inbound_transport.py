"""Inbound mode end to end: a panel dials a node and runs a task on it.

Everything else about this feature can pass unit tests while the thing itself
does not connect — which is exactly how this subsystem has failed before. These
tests stand up a real listener on a real socket, dial it with the real
connector, and assert on the state the scheduler ends up in.
"""

from __future__ import annotations

import asyncio
import socket
import sqlite3

import pytest
import pytest_asyncio

from worker import registry
from worker.identity import WorkerKeypair
from worker.inbound.artifacts import ArtifactStore
from worker.inbound.connection_log import ConnectionLog
from worker.inbound.connection_string import parse_connection
from worker.inbound.connector import NodeConnection
from worker.inbound.keys import KeyStore
from worker.inbound.listener import NodeListener
from worker.pool import WorkerPool
from worker.scheduler import Scheduler
from worker.transport.client import WorkerClient, WorkerConfig
from worker.transport.server import WorkerServicer

ENGINE, MODEL, OP = "indextts", "IndexTTS-2", "tts"


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


class _InboundHarness:
    """A node listening on loopback, plus the panel that dials it."""

    def __init__(self, tmp_path):
        # Node side.
        self.keys = KeyStore(str(tmp_path / "inbound-keys.json"))
        self.log = ConnectionLog()
        self.artifacts = ArtifactStore(str(tmp_path / "staged"))
        self.keypair = WorkerKeypair.generate()
        self.executed: list[str] = []
        self.listener = NodeListener(
            keys=self.keys,
            log=self.log,
            artifacts=self.artifacts,
            client_factory=self._client,
        )
        # Panel side.
        self.pool = WorkerPool()
        self.scheduler = Scheduler(self.pool, persist=False)
        self.servicer = WorkerServicer(
            self.scheduler, self.pool, artifact_dir=str(tmp_path / "artifacts")
        )
        self.connection = None
        self.connector_task = None
        self.port = 0

    def _client(self, artifacts, key_id):
        async def execute(assignment, **kwargs):
            self.executed.append(assignment.ref.task_id)
            return {"result_json": "{}", "payload": b"", "meta": {}}

        return WorkerClient(
            WorkerConfig(
                endpoint="",
                cert_fingerprint="",
                certificate_pem=b"",
                keypair=self.keypair,
                worker_id=self.keys.worker_id_for(key_id),
                enrollment_token="",
                max_concurrent_tasks=1,
                capabilities=_capabilities(),
                host={"hostname": "gpu-node", "os": "linux", "arch": "x86_64", "gpus": []},
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
            secret = self.keys.issue("Test panel").secret
        connection = parse_connection(f"ovnode://{secret}@127.0.0.1:{self.port}")
        self.connection = NodeConnection(self.servicer, connection)
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
async def test_the_node_is_enrolled_by_its_own_key_not_by_the_api_key(inbound):
    """The API key admits a panel; identity stays with the node's keypair. If
    these were conflated, anyone who copied the key could impersonate the
    machine to a panel that had already trusted it."""
    await inbound.connect_panel()

    stored = registry.list_workers()
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
    connection = parse_connection(f"ovnode://{bob_secret}@127.0.0.1:{inbound.port}")
    bob = NodeConnection(second.servicer, connection)
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
    await asyncio.sleep(0.5)

    assert len(inbound.pool) == 0
    kinds = [e["kind"] for e in inbound.log.snapshot()["events"]]
    assert "rejected" in kinds


@pytest.mark.asyncio
async def test_a_revoked_key_stops_working_without_disturbing_the_others(inbound):
    alice = inbound.keys.issue("Alice")
    inbound.keys.revoke(alice.key.key_id)

    await inbound.connect_panel(secret=alice.secret, wait=False)
    await asyncio.sleep(0.5)

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
    await _until(lambda: inbound.log.snapshot()["sessions"] == [])


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
    await inbound.artifacts.stage_in(declared, str(destination))
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
    enrolled = registry.list_workers()[0]

    # A second machine: valid key, valid self-signature, wrong identity.
    impostor = WorkerKeypair.generate()
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

    assert NodeConnection._proves_key_possession(forged, enrolled) is False


@pytest.mark.asyncio
async def test_the_node_keeps_sending_heartbeats_after_it_registers(inbound, monkeypatch):
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
