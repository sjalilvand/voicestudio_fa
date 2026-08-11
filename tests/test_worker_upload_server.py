"""Artifact transfer at the control-plane boundary.

The upload receiver is the one place where a remote peer writes bytes into the
user's filesystem and the app afterwards calls those bytes a finished render.
Every case here is a way that could go wrong without anybody noticing: a
transfer that stops early and is committed anyway, bytes that arrive out of
order and are appended regardless, a digest nobody checks, an artifact with no
ceiling, and — in the other direction — one worker reading the reference audio
staged for another's task.

The RPCs are driven directly rather than over a real stream: what is under test
is the integrity rule, not gRPC.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3

import pytest
import pytest_asyncio

from worker import deadlines as deadline_policy
from worker import identity, registry
from worker.clock import resolve
from worker.errors import ErrorClass, WorkerError
from worker.identity import WorkerKeypair
from worker.lifecycle import AttemptState, TaskState
from worker.pool import WorkerPool
from worker.protocol.gen import worker_v1_pb2 as pb
from worker.scheduler import Scheduler
from worker.transport import codec, server as server_module
from worker.transport.server import SESSION_METADATA_KEY, WorkerServicer

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


class _Aborted(Exception):
    """What a real gRPC ``context.abort`` does: it raises."""

    def __init__(self, code, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class _Context:
    def __init__(self, token: str = "") -> None:
        self.token = token

    def peer(self) -> str:
        return "ipv4:127.0.0.1:5555"

    def invocation_metadata(self):
        return ((SESSION_METADATA_KEY, self.token),) if self.token else ()

    async def abort(self, code, detail):
        raise _Aborted(code, detail)


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
    """A servicer with one enrolled worker, driven RPC by RPC."""

    def __init__(self, tmp_path) -> None:
        self.artifact_dir = str(tmp_path / "artifacts")
        self.pool = WorkerPool()
        self.scheduler = Scheduler(self.pool)
        self.servicer = WorkerServicer(
            self.scheduler, self.pool, artifact_dir=self.artifact_dir
        )
        self.keypair = WorkerKeypair.generate()
        self.worker_id = ""
        self.epoch = 0

    async def register(self) -> None:
        token = registry.create_enrollment(endpoint="localhost:1", cert_fingerprint="fp").encode()
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
                public_key=self.keypair.public_bytes(),
                challenge=challenge,
                challenge_signature=signature,
                nonce=nonce,
                key_id=self.keypair.key_id,
                host=codec.host_to_pb({"hostname": "gpu2", "os": "linux", "arch": "x86_64"}),
                capabilities=[codec.capability_to_pb(c) for c in _capabilities()],
                max_concurrent_tasks=2,
            ),
            _Context(),
        )
        assert not response.error.code, response.error.code
        self.worker_id = response.worker_id
        self.epoch = response.session_epoch

    @property
    def token(self) -> str:
        return self.servicer._sessions[self.worker_id].session.token

    def running(self):
        """One task assigned to this worker and rendering."""
        task = self.scheduler.submit(operation=OP, engine=ENGINE, model_id=MODEL)
        assignment = self.scheduler.next_assignment()
        assert assignment is not None
        attempt = assignment.attempt
        self.scheduler.on_accepted(task.task_id, attempt.attempt_id, epoch=attempt.session_epoch)
        self.scheduler.on_started(task.task_id, attempt.attempt_id, epoch=attempt.session_epoch)
        return task, attempt

    def final_path(self, task, attempt) -> str:
        return os.path.join(self.artifact_dir, task.task_id, f"{attempt.attempt_id}.bin")

    async def upload(self, chunks) -> pb.ResultAck:
        return await self.servicer.UploadResult(_aiter(chunks), _Context(self.token))

    async def download(self, ref, *, context=None):
        collected = []
        async for chunk in self.servicer.DownloadArtifact(ref, context or _Context(self.token)):
            collected.append(chunk)
        return collected


@pytest_asyncio.fixture
async def plane(tmp_path, db):
    p = _Plane(tmp_path)
    await p.register()
    return p


async def _aiter(items):
    for item in items:
        yield item


def _ref(plane, task, attempt, *, payload=b"", sha256=None, size=None) -> pb.ArtifactRef:
    return pb.ArtifactRef(
        artifact_id="",
        task_id=task.task_id,
        attempt_id=attempt.attempt_id,
        filename="result.wav",
        size_bytes=len(payload) if size is None else size,
        sha256=hashlib.sha256(payload).hexdigest() if sha256 is None else sha256,
        session_token=plane.token,
    )


def _chunks(ref, payload: bytes, *, size: int = 4, last: bool = True):
    """Split ``payload`` into offset-correct chunks."""
    out = []
    for start in range(0, len(payload), size):
        out.append(pb.ResultChunk(ref=ref, offset=start, data=payload[start : start + size]))
    if out and last:
        out[-1].last = True
    return out


# ── Commit only against a verified, complete transfer ──────────────────────


@pytest.mark.asyncio
async def test_a_verified_upload_commits_under_its_own_attempt(plane):
    task, attempt = plane.running()
    payload = b"rendered audio bytes"
    ref = _ref(plane, task, attempt, payload=payload)

    ack = await plane.upload(_chunks(ref, payload))

    assert ack.committed is True
    assert ack.bytes_received == len(payload)
    final = plane.final_path(task, attempt)
    assert open(final, "rb").read() == payload
    assert not os.path.exists(f"{final}.part")
    # The id handed back is store-relative, and re-resolves to what was
    # written — the worker never learns our filesystem layout.
    assert not os.path.isabs(ack.artifact_id)
    assert plane.servicer._contained_artifact(ack.artifact_id) == final


@pytest.mark.asyncio
async def test_a_stream_that_ends_without_a_last_chunk_commits_nothing(plane):
    """The iterator simply stopping is a truncated transfer, not a result.

    This committed whatever had arrived, renamed it into place, and returned
    committed=True — so a dropped connection two thirds of the way through a
    render delivered two thirds of a render as the finished article.
    """
    task, attempt = plane.running()
    payload = b"half a render, and then the link died"
    ref = _ref(plane, task, attempt, payload=payload)

    ack = await plane.upload(_chunks(ref, payload[:12], last=False))

    assert ack.committed is False
    assert ack.error.code == "UPLOAD_INCOMPLETE"
    assert ack.bytes_received == 12
    final = plane.final_path(task, attempt)
    assert not os.path.exists(final)
    # Kept, so the resume has something to resume onto.
    assert os.path.getsize(f"{final}.part") == 12


@pytest.mark.asyncio
async def test_a_digest_mismatch_is_never_renamed_into_place(plane):
    task, attempt = plane.running()
    payload = b"corrupted on the wire"
    # Same length, different bytes: only the digest can tell these apart.
    ref = _ref(plane, task, attempt, payload=b"what the worker sent!")

    ack = await plane.upload(_chunks(ref, payload))

    assert ack.committed is False
    assert ack.error.code == "DIGEST_MISMATCH"
    final = plane.final_path(task, attempt)
    assert not os.path.exists(final)
    # And the bad bytes are gone: a resume must not append onto them.
    assert not os.path.exists(f"{final}.part")


@pytest.mark.asyncio
async def test_an_upload_with_no_declared_digest_is_refused_before_any_bytes(plane):
    task, attempt = plane.running()
    payload = b"unverifiable"
    ref = _ref(plane, task, attempt, payload=payload, sha256="")

    ack = await plane.upload(_chunks(ref, payload))

    assert ack.committed is False
    assert ack.error.code == "DIGEST_REQUIRED"
    assert not os.path.exists(f"{plane.final_path(task, attempt)}.part")


@pytest.mark.asyncio
async def test_a_size_that_disagrees_with_the_bytes_delivered_is_refused(plane):
    task, attempt = plane.running()
    payload = b"eight..."
    ref = _ref(plane, task, attempt, payload=payload, size=len(payload) + 4)

    ack = await plane.upload(_chunks(ref, payload))

    assert ack.committed is False
    assert ack.error.code == "SIZE_MISMATCH"
    assert not os.path.exists(plane.final_path(task, attempt))


# ── Offsets are checked, and the ack is the bytes-held probe ───────────────


@pytest.mark.asyncio
async def test_a_chunk_at_the_wrong_offset_is_refused_with_the_bytes_held(plane):
    """``chunk.offset`` was read as a truthiness flag and then ignored, so a
    gap or an overlap was appended as though it were the next byte."""
    task, attempt = plane.running()
    payload = b"0123456789abcdef"
    ref = _ref(plane, task, attempt, payload=payload)
    stream = [
        pb.ResultChunk(ref=ref, offset=0, data=payload[:4]),
        pb.ResultChunk(ref=ref, offset=999, data=payload[4:], last=True),
    ]

    ack = await plane.upload(stream)

    assert ack.committed is False
    assert ack.error.code == "OFFSET_MISMATCH"
    # The only report of "bytes already held" this RPC can make: one terminal
    # ack, carrying the offset to resume from.
    assert ack.bytes_received == 4
    assert not os.path.exists(plane.final_path(task, attempt))


@pytest.mark.asyncio
async def test_a_resume_hashes_the_bytes_already_on_disk(plane):
    """Otherwise the digest would attest only to the resumed tail — verifying
    the half of the file that was never in doubt."""
    task, attempt = plane.running()
    payload = b"the first half of it | and the second half of it"
    ref = _ref(plane, task, attempt, payload=payload)

    dropped = await plane.upload(_chunks(ref, payload[:20], last=False))
    assert dropped.bytes_received == 20

    resumed = await plane.upload(
        [pb.ResultChunk(ref=ref, offset=20, data=payload[20:], last=True)]
    )

    assert resumed.committed is True
    assert resumed.bytes_received == len(payload)
    assert open(plane.final_path(task, attempt), "rb").read() == payload


@pytest.mark.asyncio
async def test_a_resume_onto_corrupted_held_bytes_still_fails_verification(plane):
    task, attempt = plane.running()
    payload = b"the first half of it | and the second half of it"
    ref = _ref(plane, task, attempt, payload=payload)
    await plane.upload(_chunks(ref, b"tampered with here!!", last=False))

    resumed = await plane.upload(
        [pb.ResultChunk(ref=ref, offset=20, data=payload[20:], last=True)]
    )

    assert resumed.committed is False
    assert resumed.error.code == "DIGEST_MISMATCH"
    assert not os.path.exists(plane.final_path(task, attempt))


# ── Ceilings ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_upload_past_its_declared_size_is_cut_off(plane):
    """A declared size narrows the cap; it cannot be exceeded by streaming."""
    task, attempt = plane.running()
    ref = _ref(plane, task, attempt, payload=b"tiny", size=4)

    ack = await plane.upload(_chunks(ref, b"very much larger than four bytes"))

    assert ack.committed is False
    assert ack.error.code == "ARTIFACT_TOO_LARGE"
    final = plane.final_path(task, attempt)
    assert not os.path.exists(final)
    assert not os.path.exists(f"{final}.part")


@pytest.mark.asyncio
async def test_an_undeclared_upload_is_bounded_by_the_artifact_ceiling(plane, monkeypatch):
    monkeypatch.setattr(server_module, "MAX_ARTIFACT_BYTES", 8)
    task, attempt = plane.running()
    ref = _ref(plane, task, attempt, payload=b"sixteen bytes!!!", size=0)

    ack = await plane.upload(_chunks(ref, b"sixteen bytes!!!"))

    assert ack.committed is False
    assert ack.error.code == "ARTIFACT_TOO_LARGE"


@pytest.mark.asyncio
async def test_the_per_task_artifact_budget_is_enforced_across_attempts(plane, monkeypatch):
    """One artifact under the cap, twice, must not add up to more than a task
    is allowed to deliver."""
    monkeypatch.setattr(server_module, "MAX_TASK_ARTIFACT_BYTES", 24)
    task, attempt = plane.running()
    payload = b"sixteen bytes!!!"
    first = await plane.upload(_chunks(ref := _ref(plane, task, attempt, payload=payload), payload))
    assert first.committed is True
    assert ref.size_bytes == 16

    # A second attempt of the same task, delivering another 16 bytes. CAPACITY
    # so the retry can land on the same worker — anything else excludes it.
    plane.scheduler.on_failed(
        task.task_id,
        attempt.attempt_id,
        WorkerError(error_class=ErrorClass.CAPACITY, code="RETRY", message="again"),
        epoch=attempt.session_epoch,
    )
    retry = plane.scheduler.next_assignment()
    assert retry is not None
    plane.scheduler.on_accepted(task.task_id, retry.attempt.attempt_id, epoch=retry.attempt.session_epoch)
    plane.scheduler.on_started(task.task_id, retry.attempt.attempt_id, epoch=retry.attempt.session_epoch)

    ack = await plane.upload(
        _chunks(_ref(plane, task, retry.attempt, payload=payload), payload)
    )

    assert ack.committed is False
    assert ack.error.code == "TASK_BUDGET_EXCEEDED"


# ── The delivery phase actually exists ─────────────────────────────────────


@pytest.mark.asyncio
async def test_an_upload_moves_the_task_into_result_uploading(plane):
    """``Task.uploading`` had zero callers, so RESULT_UPLOADING was
    unreachable and every byte of delivery ran under the execution phase."""
    task, attempt = plane.running()
    payload = b"0123456789abcdef"
    ref = _ref(plane, task, attempt, payload=payload)
    seen: list[TaskState] = []

    async def observed():
        for chunk in _chunks(ref, payload):
            yield chunk
            seen.append(task.state)

    ack = await plane.servicer.UploadResult(observed(), _Context(plane.token))

    assert ack.committed is True
    assert seen[0] is TaskState.RESULT_UPLOADING
    assert attempt.state is AttemptState.UPLOADING


@pytest.mark.asyncio
async def test_the_upload_lease_runs_on_the_result_delivery_budget(plane):
    """A slow delivery is bounded by ``result_delivery_seconds`` (900s), not by
    the execution budget it used to inherit — which is what made a large
    upload die mid-transfer under the 120s progress lease."""
    task, attempt = plane.running()
    budget = deadline_policy.for_task(OP)
    payload = b"0123456789abcdef"
    ref = _ref(plane, task, attempt, payload=payload)

    async def slow():
        chunks = _chunks(ref, payload)
        yield chunks[0]
        # Age the delivery phase past the execution budget but well inside the
        # delivery one. Under the old code there was no delivery phase, so the
        # keepalive ceiling clamped the lease into the past and the next sweep
        # would have failed a task that was uploading fine.
        attempt.phase_started_at = resolve(None) - (budget.execution_seconds + 60)
        for chunk in chunks[1:]:
            yield chunk

    ack = await plane.servicer.UploadResult(slow(), _Context(plane.token))

    assert ack.committed is True
    assert budget.result_delivery_seconds > budget.execution_seconds + 60
    assert not attempt.lease_expired()


def test_upload_keepalive_does_not_move_completed_progress_backwards(plane):
    task, attempt = plane.running()
    plane.scheduler.on_progress(
        task.task_id, attempt.attempt_id, progress=1.0, epoch=attempt.session_epoch
    )

    plane.servicer._renew_upload_lease(attempt)

    assert attempt.progress == 1.0


@pytest.mark.asyncio
async def test_an_upload_onto_a_cancelled_task_is_refused(plane):
    task, attempt = plane.running()
    payload = b"too late"
    ref = _ref(plane, task, attempt, payload=payload)
    plane.scheduler.cancel(task.task_id)

    ack = await plane.upload(_chunks(ref, payload))

    assert ack.committed is False
    assert ack.error.code == "ATTEMPT_NOT_LIVE"
    assert not os.path.exists(plane.final_path(task, attempt))


@pytest.mark.asyncio
async def test_an_upload_for_another_workers_attempt_is_refused(plane):
    task, attempt = plane.running()
    payload = b"not yours"
    ref = _ref(plane, task, attempt, payload=payload)
    plane.servicer._sessions[plane.worker_id].worker_id = "someone-else"

    ack = await plane.upload(_chunks(ref, payload))

    assert ack.committed is False
    assert ack.error.code == "UNKNOWN_ATTEMPT"
    assert not os.path.exists(plane.final_path(task, attempt))


# ── Serving staged inputs ──────────────────────────────────────────────────


def _stage(plane, name: str, data: bytes) -> str:
    """Stand in for the input-staging step: a file inside the artifact store."""
    path = os.path.join(plane.artifact_dir, "inputs", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return os.path.join("inputs", name)


@pytest.mark.asyncio
async def test_a_worker_can_read_the_input_staged_for_its_own_task(plane):
    task, attempt = plane.running()
    artifact_id = _stage(plane, "voice.wav", b"reference audio" * 10)

    chunks = await plane.download(
        pb.ArtifactRef(
            artifact_id=artifact_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            session_token=plane.token,
        )
    )

    assert b"".join(c.data for c in chunks) == b"reference audio" * 10
    assert chunks[-1].last is True
    assert chunks[0].ref.size_bytes == len(b"reference audio" * 10)
    # Nothing hands a session token back out that did not have to go out.
    assert all(not c.ref.session_token for c in chunks)


@pytest.mark.asyncio
async def test_dispatch_stages_and_serves_from_the_servicers_artifact_root(plane, tmp_path):
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"reference audio")
    task = plane.scheduler.submit(
        operation=OP, engine=ENGINE, model_id=MODEL, params={"ref_audio": str(voice)}
    )
    assignment = plane.scheduler.next_assignment()
    assert assignment is not None

    assert await plane.servicer.dispatch(assignment)
    message = await plane.servicer._sessions[plane.worker_id].outbox.get()
    wire = message.assignment
    assert wire.inputs
    staged = os.path.join(plane.artifact_dir, wire.inputs[0].artifact_id)
    assert os.path.isfile(staged)

    chunks = await plane.download(
        pb.ArtifactRef(
            artifact_id=wire.inputs[0].artifact_id,
            task_id=task.task_id,
            attempt_id=assignment.attempt.attempt_id,
            session_token=plane.token,
        )
    )
    assert b"".join(chunk.data for chunk in chunks) == voice.read_bytes()


@pytest.mark.asyncio
async def test_a_worker_cannot_read_an_input_for_a_task_it_is_not_running(plane):
    """Authentication is not authorisation: from this phase on, staged inputs
    are the user's own reference audio."""
    task, attempt = plane.running()
    artifact_id = _stage(plane, "voice.wav", b"reference audio")
    plane.servicer._sessions[plane.worker_id].worker_id = "someone-else"

    with pytest.raises(_Aborted) as caught:
        await plane.download(
            pb.ArtifactRef(
                artifact_id=artifact_id,
                task_id=task.task_id,
                attempt_id=attempt.attempt_id,
                session_token=plane.token,
            )
        )

    assert "PERMISSION_DENIED" in str(caught.value.code)


@pytest.mark.asyncio
async def test_an_input_request_naming_no_task_is_refused(plane):
    plane.running()
    artifact_id = _stage(plane, "voice.wav", b"reference audio")

    with pytest.raises(_Aborted) as caught:
        await plane.download(
            pb.ArtifactRef(artifact_id=artifact_id, session_token=plane.token)
        )

    assert "PERMISSION_DENIED" in str(caught.value.code)


@pytest.mark.asyncio
async def test_an_input_outside_the_artifact_store_is_not_served(plane, tmp_path):
    task, attempt = plane.running()
    secret = tmp_path / "secret.txt"
    secret.write_text("private")

    for artifact_id in ("../secret.txt", str(secret), "/etc/passwd"):
        with pytest.raises(_Aborted) as caught:
            await plane.download(
                pb.ArtifactRef(
                    artifact_id=artifact_id,
                    task_id=task.task_id,
                    attempt_id=attempt.attempt_id,
                    session_token=plane.token,
                )
            )
        assert "NOT_FOUND" in str(caught.value.code)
