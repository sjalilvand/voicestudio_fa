"""Control-plane gRPC service.

Translates the wire into scheduler calls and back. The rules it enforces here
are the ones that must hold at the *boundary*, before anything reaches the
domain:

  * authentication — an enrollment token once, then proof of key possession
  * fencing — one active session per worker, newest epoch wins, stale epochs
    dropped rather than merged
  * ordering — persist a result before acknowledging it

Everything else is delegated. If this file starts making scheduling decisions,
something has been put in the wrong place.

The control stream runs as two independent loops rather than a single
request/response generator. That is not stylistic: a worker uploading its
status while the server is trying to push an assignment would otherwise
deadlock behind its own reader, and the heartbeats that prove the worker is
alive are exactly what must never queue behind anything else.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

import grpc

from core.path_security import UnsafePath, resolve_within, safe_filename
from worker import identity, registry, task_store
from worker.errors import ErrorClass, WorkerError
from worker.lifecycle import Attempt, Task
from worker.pool import WorkerPool
from worker.protocol.gen import worker_v1_pb2 as pb
from worker.protocol.gen import worker_v1_pb2_grpc as pb_grpc
from worker.scheduler import Scheduler
from worker.transport import codec

logger = logging.getLogger("omnivoice.worker")

PROTOCOL_VERSION = 1
# How far back a peer may be and still be served. Beta ships continuously, so
# skew is the normal case rather than the exception.
MIN_SUPPORTED_VERSION = 1

# Metadata key carrying the session token when a worker opens its stream.
SESSION_METADATA_KEY = "x-omnivoice-session"

# Bytes above which a result must be uploaded rather than inlined on the
# control stream. Kept well under gRPC's 4 MB default message cap: a large
# payload here head-of-line blocks the heartbeats that prove the worker alive.
INLINE_RESULT_THRESHOLD = 256 * 1024

_HEARTBEAT_INTERVAL_SECONDS = 20
# How often the control plane times a round trip to each worker. Frequent
# enough that the latency shown in the UI is current, rare enough to be free.
_PING_INTERVAL_SECONDS = 5.0


class _Session:
    """Server-side view of one connected worker's stream."""

    def __init__(self, worker_id: str, epoch: int, session: identity.Session) -> None:
        self.worker_id = worker_id
        self.epoch = epoch
        self.session = session
        self.outbox: asyncio.Queue[pb.ServerMessage] = asyncio.Queue()
        self.stream_open = False
        # nonce → monotonic send time, for the outstanding ping.
        self.pending_pings: dict[int, float] = {}
        self.next_nonce = 1

    async def send(self, message: pb.ServerMessage) -> None:
        await self.outbox.put(message)


class WorkerServicer(pb_grpc.WorkerServiceServicer):
    """Implements ``WorkerService`` on top of the scheduler and registry."""

    def __init__(
        self,
        scheduler: Scheduler,
        pool: WorkerPool,
        *,
        artifact_dir: str,
        cert_fingerprint: str = "",
    ) -> None:
        self.scheduler = scheduler
        self.pool = pool
        self.artifact_dir = artifact_dir
        self.cert_fingerprint = cert_fingerprint
        self._sessions: dict[str, _Session] = {}
        self._by_token: dict[str, _Session] = {}
        os.makedirs(artifact_dir, exist_ok=True)

    # ── Registration ──────────────────────────────────────────────────────

    async def Register(self, request: pb.RegisterRequest, context) -> pb.RegisterResponse:
        if request.protocol_version_max < MIN_SUPPORTED_VERSION:
            return self._refuse(
                "UPGRADE_REQUIRED",
                "This worker speaks an older protocol than the control plane supports. "
                "Update OmniVoice on the worker machine, then reconnect.",
            )
        if request.protocol_version_min > PROTOCOL_VERSION:
            return self._refuse(
                "UPGRADE_REQUIRED",
                "This worker is newer than the control plane. Update OmniVoice on this "
                "machine, then reconnect.",
            )

        worker = self._authenticate(request)
        if worker is None:
            # Deliberately one message for every failure mode: unknown key,
            # revoked worker, bad signature, spent token. Distinguishing them
            # tells an attacker which half of the guess was right.
            return self._refuse(
                "AUTH_FAILED",
                "This worker could not be authenticated. Generate a new enrollment "
                "token in Settings → System → Remote workers and add the worker again.",
            )

        epoch = registry.begin_session(worker.id)
        session = identity.issue_session(worker_id=worker.id, key_id=worker.key_id, epoch=epoch)
        capabilities = [codec.capability_from_pb(c) for c in request.capabilities]
        host = codec.host_from_pb(request.host)
        registry.update_capabilities(
            worker.id,
            capabilities=capabilities,
            host=host,
            max_concurrent_tasks=request.max_concurrent_tasks or 1,
        )
        worker = registry.get(worker.id) or worker

        backend = host["gpus"][0].get("backend", "") if host.get("gpus") else ""
        claimed = {ref.attempt_id for ref in request.in_flight}
        # A finished result the worker never had acknowledged is work it is
        # still holding the only copy of. Reconciliation writes off anything
        # the worker does not claim (lifecycle.reconcile), so leaving these out
        # marks a completed render LOST moments before it is redelivered.
        unacked = {ref.attempt_id for ref in request.completed_unacked}
        # The address the worker actually reached us from — what the UI shows
        # as ip:port. Self-reported endpoints would be guesses; this is fact.
        address = _peer_address(context)

        # Replace any previous session for this worker. Two live sessions is
        # the race that delivers two accepts for one assignment.
        previous = self._sessions.pop(worker.id, None)
        if previous is not None:
            self._by_token.pop(previous.session.token, None)

        self.pool.connect(
            worker,
            session=session,
            epoch=epoch,
            max_concurrent_tasks=request.max_concurrent_tasks or 1,
            backend=backend,
            in_flight=claimed,
            address=address,
        )
        self.pool.apply_capabilities(worker.id, capabilities)
        live = _Session(worker.id, epoch, session)
        self._sessions[worker.id] = live
        self._by_token[session.token] = live

        # Reconcile before any new work is dispatched: the worker may be
        # holding tasks this control plane forgot across a restart. Unacked
        # results count as held here but not as occupied slots above — the work
        # is done, only its delivery is outstanding.
        self.scheduler.on_reconnected(worker.id, in_flight=claimed | unacked)

        logger.info("Worker %s registered on epoch %d", worker.name, epoch)
        return pb.RegisterResponse(
            worker_id=worker.id,
            session_token=session.token,
            session_epoch=epoch,
            protocol_version=PROTOCOL_VERSION,
            session_expires_at_unix=int(session.expires_at),
            heartbeat_interval_seconds=_HEARTBEAT_INTERVAL_SECONDS,
            authoritative_in_flight=self._authoritative_refs(worker.id),
        )

    def _authenticate(self, request: pb.RegisterRequest) -> Optional[registry.RemoteWorker]:
        public_key = bytes(request.public_key)
        if len(public_key) != 32:
            return None
        key_id = identity.key_id_for(public_key)

        if request.enrollment_token:
            # First contact: spend the join token, then bind this key to it.
            try:
                token = identity.EnrollmentToken.decode(request.enrollment_token)
            except ValueError:
                return None
            if token.expired():
                return None
            if registry.is_revoked(key_id):
                return None
            existing = registry.get_by_key_id(key_id)
            if not registry.redeem_enrollment(token, worker_id=existing.id if existing else key_id):
                return None
            return registry.enroll_worker(
                name=request.host.hostname or key_id,
                public_key=public_key,
                consent_granted=True,
            )

        if registry.is_revoked(key_id):
            return None
        return registry.authenticate(
            key_id=key_id,
            public_key=public_key,
            challenge=bytes(request.challenge),
            signature=bytes(request.challenge_signature),
            nonce=bytes(request.nonce),
            session_epoch=request.envelope.sequence,
        )

    def _authoritative_refs(self, worker_id: str) -> list[pb.TaskRef]:
        """What this control plane believes the worker is running.

        Anything the worker holds that is not in this list is a zombie it must
        stop, which is the other half of reconciliation.
        """
        refs = []
        for task in self.scheduler.tasks_for_worker(worker_id):
            attempt = task.active_attempt
            if attempt is not None:
                refs.append(codec.ref_for(attempt))
        return refs

    @staticmethod
    def _refuse(code: str, message: str) -> pb.RegisterResponse:
        return pb.RegisterResponse(
            error=pb.Error(error_class=pb.ERROR_CLASS_PROTOCOL, code=code, message=message)
        )

    # ── Control stream ────────────────────────────────────────────────────

    async def Control(self, request_iterator, context) -> None:
        """Bidirectional control stream.

        A coroutine (not an async generator) so that reads and writes can run
        as independent tasks: outbound assignments must not wait on an inbound
        message, and heartbeats must not queue behind an outbound one.
        """
        session = self._session_from_metadata(context)
        if session is None:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Register before opening a control stream.",
            )
            return
        if session.stream_open:
            await context.abort(
                grpc.StatusCode.ALREADY_EXISTS, "This session already has an open stream."
            )
            return

        session.stream_open = True
        writer = asyncio.create_task(self._write_loop(session, context))
        reader = asyncio.create_task(self._read_loop(session, request_iterator))
        pinger = asyncio.create_task(self._ping_loop(session))
        try:
            done, pending = await asyncio.wait(
                {reader, writer, pinger}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, asyncio.CancelledError):
                    logger.debug("Control stream ended for %s: %s", session.worker_id, exc)
        finally:
            session.stream_open = False
            for task in (reader, writer, pinger):
                task.cancel()
            # A dropped stream starts grace windows; it fails nothing. The
            # worker may be seconds away from delivering a finished result.
            self.scheduler.on_disconnected(session.worker_id)
            self._sessions.pop(session.worker_id, None)
            self._by_token.pop(session.session.token, None)
            logger.info("Worker %s disconnected", session.worker_id)

    def _session_from_metadata(self, context) -> Optional[_Session]:
        for key, value in context.invocation_metadata() or ():
            if key.lower() == SESSION_METADATA_KEY:
                session = self._by_token.get(value)
                if session is not None and not session.session.expired():
                    return session
                return None
        return None

    async def _read_loop(self, session: _Session, request_iterator) -> None:
        async for message in request_iterator:
            try:
                await self._handle(session, message)
            except Exception:
                # One unusable frame is not a broken session. A late or
                # out-of-order message raises LifecycleError from the domain,
                # and letting that end the reader would win the asyncio.wait in
                # Control() and disconnect a worker that is mid-render.
                logger.warning(
                    "Dropping unusable %s frame from worker %s",
                    message.WhichOneof("payload"),
                    session.worker_id,
                    exc_info=True,
                )

    async def _ping_loop(self, session: _Session) -> None:
        """Time a round trip periodically so the UI can show real latency."""
        while True:
            await asyncio.sleep(_PING_INTERVAL_SECONDS)
            nonce = session.next_nonce
            session.next_nonce += 1
            # Monotonic: a wall-clock jump (NTP, sleep/wake) must not turn into
            # a nonsense latency reading.
            session.pending_pings[nonce] = time.monotonic()
            # Never let unanswered pings accumulate on a wedged worker.
            if len(session.pending_pings) > 20:
                for stale in sorted(session.pending_pings)[:-5]:
                    session.pending_pings.pop(stale, None)
            await session.send(pb.ServerMessage(ping=pb.Ping(nonce=nonce)))

    async def _write_loop(self, session: _Session, context) -> None:
        while True:
            message = await session.outbox.get()
            await context.write(message)

    async def _handle(self, session: _Session, message: pb.WorkerMessage) -> None:
        kind = message.WhichOneof("payload")
        if kind is None:
            return

        if kind == "heartbeat":
            beat = message.heartbeat
            self.pool.heartbeat(
                session.worker_id,
                active_tasks=beat.active_tasks,
                available_slots=beat.available_slots,
                resident_models=set(beat.resident_models),
                free_memory_bytes=beat.free_memory_bytes,
            )
            registry.touch(session.worker_id)
            return

        if kind == "capabilities":
            caps = [codec.capability_from_pb(c) for c in message.capabilities.capabilities]
            registry.update_capabilities(session.worker_id, capabilities=caps)
            self.pool.apply_capabilities(session.worker_id, caps)
            return

        if kind == "goodbye":
            # A clean shutdown is a drain, not a failure.
            worker = self.pool.get(session.worker_id)
            if worker is not None:
                worker.draining = True
            return

        if kind == "pong":
            sent_at = session.pending_pings.pop(message.pong.nonce, None)
            if sent_at is not None:
                self.pool.record_latency(
                    session.worker_id, (time.monotonic() - sent_at) * 1000.0
                )
            return

        if kind == "cancel_ack":
            return

        if kind == "result":
            # Deliberately ahead of the epoch fence. A result is a statement
            # about a *past* epoch by construction — the work was assigned in
            # the session the reconnect just replaced — so fencing it on the
            # live epoch drops finished renders. Ownership is checked against
            # the attempt's recorded epoch instead, inside _on_result.
            await self._on_result(session, message.result)
            return

        ref = getattr(message, kind).ref
        if not self._owns(session, ref):
            return

        if kind == "accepted":
            self.scheduler.on_accepted(ref.task_id, ref.attempt_id, epoch=ref.session_epoch)
        elif kind == "rejected":
            error = codec.error_from_pb(message.rejected.error) or WorkerError(
                error_class=ErrorClass.CAPACITY,
                code="WORKER_AT_CAPACITY",
                message="The worker declined the task.",
            )
            self.scheduler.on_failed(ref.task_id, ref.attempt_id, error, epoch=ref.session_epoch)
        elif kind == "model_loading":
            self.scheduler.on_model_loading(
                ref.task_id,
                ref.attempt_id,
                progress=message.model_loading.progress,
                detail=message.model_loading.detail,
                epoch=ref.session_epoch,
            )
        elif kind == "started":
            self.scheduler.on_started(ref.task_id, ref.attempt_id, epoch=ref.session_epoch)
        elif kind == "progress":
            # The lease arithmetic lives in the scheduler, which owns the
            # phase budgets; the transport only reports what arrived. A
            # keepalive frame renews without claiming any work was done.
            self.scheduler.on_progress(
                ref.task_id,
                ref.attempt_id,
                progress=message.progress.progress,
                stage=message.progress.stage,
                keepalive=message.progress.keepalive,
                epoch=ref.session_epoch,
            )
        elif kind == "failed":
            error = codec.error_from_pb(message.failed.error) or WorkerError(
                error_class=ErrorClass.TRANSIENT,
                code="WORKER_FAILED",
                message="The worker reported a failure with no detail.",
            )
            self.scheduler.on_failed(ref.task_id, ref.attempt_id, error, epoch=ref.session_epoch)

    def _owns(self, session: _Session, ref: pb.TaskRef) -> bool:
        """May this session speak for the attempt the frame names?

        Ownership, deliberately not an epoch comparison. ``ref.session_epoch``
        is stamped once at dispatch and echoed verbatim by the worker for the
        life of the task, while ``registry.begin_session`` bumps the session
        epoch on every reconnect. Fencing task frames against the *live* epoch
        therefore discarded every liveness frame from a worker that dropped and
        resumed — so the control plane expired a task whose GPU was still
        rendering it, and swallowed the failure report when it went wrong.

        Staleness is still fenced, one layer down and per attempt:
        ``Scheduler._fenced`` compares the frame's epoch against the epoch the
        *attempt* was assigned under, which is the question that actually
        matters. What only this layer can check is that the session on the
        stream is the worker the attempt was handed to.
        """
        attempt, foreign = self._attempt_and_owner(session, ref)
        if foreign:
            # Not a routine race: unguessable ids and no listing RPC mean a
            # worker should never see another's attempt id.
            logger.warning(
                "Worker %s sent a frame for an attempt owned by another worker; dropping",
                session.worker_id,
            )
            return False
        if attempt is None:
            logger.debug("Dropping frame for unknown attempt on task %s", ref.task_id)
            return False
        return True

    async def _on_result(self, session: _Session, result: pb.TaskResult) -> None:
        """Commit, then acknowledge — never the other way round.

        The acknowledgement is the worker's licence to forget a finished
        render, so it is sent only once this control plane holds a durable
        verdict. Acking a frame we could not place — an attempt we have no
        record of, a task still being restored — silently destroys the only
        copy of work that succeeded.
        """
        ref = result.ref
        attempt, foreign = self._attempt_and_owner(session, ref)
        if foreign:
            # Committing here would mark the task done with no artifact, and
            # the owning worker's real delivery would then arrive as a
            # duplicate and be discarded — losing the render this whole
            # redelivery path exists to protect. No ack either: nothing was
            # placed, so nothing has earned the licence to forget.
            logger.warning(
                "Worker %s reported a result for an attempt owned by another worker; dropping",
                session.worker_id,
            )
            return
        payload = None
        if result.result_json:
            try:
                payload = json.loads(result.result_json)
            except ValueError:
                payload = {"raw": result.result_json}

        artifact = None
        if result.artifacts:
            artifact = self._contained_artifact(result.artifacts[0].artifact_id)
        # No attempt record, no place to put it: the payload of a task we
        # cannot identify has nothing to be attached to, and the worker keeps
        # its copy because nothing below will acknowledge it.
        if result.inline_payload and attempt is not None:
            artifact = self._store_inline(attempt, bytes(result.inline_payload))

        # Returns only after the commit is durable, which is what makes the
        # acknowledgement below safe to send. The epoch on the wire is the one
        # the attempt was assigned under, and that is what the scheduler
        # compares against — not whichever session happens to be live now.
        committed, task = self.scheduler.on_result(
            ref.task_id,
            ref.attempt_id,
            result_ref=artifact,
            result=payload,
            epoch=ref.session_epoch,
        )
        if self._settled(committed, task, ref.task_id):
            await session.send(pb.ServerMessage(result_ack=pb.ResultAckMessage(ref=ref)))

    def _settled(self, committed: bool, task: Optional[Task], task_id: str) -> bool:
        """May the worker drop its copy of this result?

        Only against a durable verdict: this commit, an earlier one that won
        the race, or — after a restart that never reloaded the task — the fact
        of completion on disk. Anything else is redelivered, which costs one
        frame per reconnect and is the only thing standing between a dropped
        message and a lost render.
        """
        if committed:
            return True
        if task is not None:
            return task.state.terminal
        try:
            return task_store.is_committed(task_id)
        except Exception:
            logger.debug("Could not check the committed state of %s", task_id, exc_info=True)
            return False

    def _attempt_for(self, session: _Session, ref) -> Optional[Attempt]:
        """This control plane's own record of the attempt a frame names.

        Every artifact path is minted from what this returns rather than from
        the frame, because the ids on the wire are remote input: ``os.path.join``
        silently discards its prefix the moment one of them is absolute.
        """
        attempt, _foreign = self._attempt_and_owner(session, ref)
        return attempt

    def _attempt_and_owner(self, session: _Session, ref) -> tuple[Optional[Attempt], bool]:
        """``(attempt, foreign)`` — the attempt, and whether another worker owns it.

        The two None cases must not be collapsed. "No record" is ordinary and
        recoverable: a task not yet restored after a restart still has a
        durable verdict on disk, so a result naming it is redelivered rather
        than lost. "Another worker's attempt" is neither — accepting it lets a
        frame from the wrong worker commit the task, after which the owning
        worker's real delivery arrives as a duplicate and its audio is
        discarded. Returning one None for both is how that got through.
        """
        task = self.scheduler.get(ref.task_id)
        if task is None:
            return None, False
        attempt = task.get_attempt(ref.attempt_id)
        if attempt is None:
            return None, False
        if attempt.worker_id != session.worker_id:
            return None, True
        return attempt, False

    def _artifact_path(self, task_id: str, attempt_id: str) -> Optional[str]:
        """Attempt-scoped storage for one result.

        Attempt-scoped, not task-scoped: two attempts of one task must never
        share a path, or a superseded straggler overwrites the result that won.
        """
        try:
            relative = os.path.join(safe_filename(task_id), f"{safe_filename(attempt_id)}.bin")
            path = resolve_within(self.artifact_dir, relative)
        except UnsafePath:
            logger.warning("Refusing to store a result outside the artifact directory")
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _contained_artifact(self, artifact_id: str) -> Optional[str]:
        """An artifact the worker names is only ever a reference into our own
        store, and is resolved as one."""
        if not artifact_id:
            return None
        try:
            return str(resolve_within(self.artifact_dir, artifact_id))
        except UnsafePath:
            logger.warning("Refusing an artifact reference outside the artifact directory")
            return None

    def _store_inline(self, attempt: Attempt, payload: bytes) -> Optional[str]:
        """Write a small inline result to attempt-scoped storage."""
        path = self._artifact_path(attempt.task_id, attempt.attempt_id)
        if path is None:
            return None
        with open(path, "wb") as fh:
            fh.write(payload)
        return path

    # ── Dispatch out ──────────────────────────────────────────────────────

    async def dispatch(self, assignment) -> bool:
        """Send an assignment to its worker. False if the stream is gone."""
        session = self._sessions.get(assignment.worker.worker_id)
        if session is None:
            return False
        await session.send(
            pb.ServerMessage(
                assignment=codec.assignment_to_pb(
                    assignment.task, assignment.attempt, assignment.deadlines
                )
            )
        )
        return True

    async def cancel(self, worker_id: str, task_id: str, attempt_id: str, epoch: int) -> bool:
        session = self._sessions.get(worker_id)
        if session is None:
            return False
        await session.send(
            pb.ServerMessage(cancel=pb.TaskCancel(ref=codec.task_ref(task_id, attempt_id, epoch)))
        )
        return True

    async def drain(self, worker_id: str, *, deadline_seconds: int = 300) -> bool:
        session = self._sessions.get(worker_id)
        if session is None:
            return False
        worker = self.pool.get(worker_id)
        if worker is not None:
            worker.draining = True
        await session.send(
            pb.ServerMessage(drain=pb.Drain(deadline_seconds=deadline_seconds))
        )
        return True

    # ── Artifact transfer ─────────────────────────────────────────────────

    async def UploadResult(self, request_iterator, context) -> pb.ResultAck:
        """Receive a result artifact in chunks, resumably.

        Written to an attempt-scoped ``.part`` file and only renamed into place
        once the last chunk lands, so a partial transfer can never be mistaken
        for a finished result.
        """
        artifact_id = ""
        received = 0
        handle = None
        path = ""
        final = ""
        try:
            async for chunk in request_iterator:
                if handle is None:
                    ref = chunk.ref
                    session = self._session_for(context, ref)
                    if session is None:
                        await context.abort(
                            grpc.StatusCode.UNAUTHENTICATED, "Unknown or expired session."
                        )
                        return pb.ResultAck(committed=False)
                    # Same rule as an inline result: the destination is minted
                    # from our own attempt record, never assembled from the ids
                    # in the request.
                    attempt = self._attempt_for(session, ref)
                    final = (
                        self._artifact_path(attempt.task_id, attempt.attempt_id)
                        if attempt is not None
                        else None
                    )
                    if final is None:
                        await context.abort(
                            grpc.StatusCode.PERMISSION_DENIED,
                            "No such attempt is running for this worker.",
                        )
                        return pb.ResultAck(committed=False)
                    artifact_id = final
                    path = f"{final}.part"
                    # Resume where a previous transfer stopped.
                    mode = "ab" if chunk.offset and os.path.exists(path) else "wb"
                    handle = open(path, mode)
                    received = handle.tell()
                handle.write(chunk.data)
                received += len(chunk.data)
                if chunk.last:
                    break
        finally:
            if handle is not None:
                handle.close()
        if path and final:
            os.replace(path, final)
            artifact_id = final
        return pb.ResultAck(artifact_id=artifact_id, bytes_received=received, committed=True)

    async def DownloadArtifact(self, request: pb.ArtifactRef, context):
        """Stream a task input (reference audio, source video) to a worker."""
        if not self._authorized(context, request):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Unknown or expired session.")
            return
        path = self._resolve_input(request.artifact_id)
        if path is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Artifact not found.")
            return
        offset = 0
        with open(path, "rb") as fh:
            while True:
                data = fh.read(64 * 1024)
                if not data:
                    break
                yield pb.ArtifactChunk(ref=request, offset=offset, data=data, last=False)
                offset += len(data)
        yield pb.ArtifactChunk(ref=request, offset=offset, data=b"", last=True)

    def _session_for(self, context, ref) -> Optional[_Session]:
        """The live session a transfer belongs to, by ref token or by metadata."""
        token = getattr(ref, "session_token", "") or ""
        if token and token in self._by_token:
            session = self._by_token[token]
            return None if session.session.expired() else session
        return self._session_from_metadata(context)

    def _authorized(self, context, ref) -> bool:
        return self._session_for(context, ref) is not None

    def _resolve_input(self, artifact_id: str) -> Optional[str]:
        """Resolve an input reference to a path inside the artifact directory.

        Containment is enforced rather than assumed: a worker is a remote peer,
        and an artifact id is attacker-controlled input, so ``../`` must not be
        able to read arbitrary files off the control plane. One containment
        implementation for the whole file — a second, hand-rolled one is how
        the two directions came to disagree in the first place.
        """
        path = self._contained_artifact(artifact_id)
        return path if path and os.path.isfile(path) else None


async def serve(
    servicer: WorkerServicer,
    *,
    host: str = "0.0.0.0",
    port: int = 7443,
    certificate_pem: bytes,
    private_key_pem: bytes,
) -> grpc.aio.Server:
    """Start the control-plane server. TLS is not optional."""
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", 8 * 1024 * 1024),
            ("grpc.max_send_message_length", 8 * 1024 * 1024),
            # Consumer NAT/CGNAT mappings expire silently after 30–120s, and a
            # dead mapping looks exactly like a healthy idle connection until
            # something asks. Keepalives make the difference observable.
            ("grpc.keepalive_time_ms", 25_000),
            ("grpc.keepalive_timeout_ms", 10_000),
            ("grpc.keepalive_permit_without_calls", 1),
        ]
    )
    pb_grpc.add_WorkerServiceServicer_to_server(servicer, server)
    credentials = grpc.ssl_server_credentials([(private_key_pem, certificate_pem)])
    server.add_secure_port(f"{host}:{port}", credentials)
    await server.start()
    logger.info("Worker control plane listening on %s:%d (TLS)", host, port)
    return server


def _peer_address(context) -> str:
    """Turn gRPC's peer string into a plain ip:port.

    gRPC reports "ipv4:192.168.0.5:54321" or "ipv6:[::1]:54321"; neither is
    something to show a user.
    """
    try:
        peer = context.peer() or ""
    except Exception:
        return ""
    if peer.startswith("ipv4:"):
        return peer[5:]
    if peer.startswith("ipv6:"):
        return peer[5:]
    return peer


__all__ = [
    "INLINE_RESULT_THRESHOLD",
    "MIN_SUPPORTED_VERSION",
    "PROTOCOL_VERSION",
    "SESSION_METADATA_KEY",
    "WorkerServicer",
    "serve",
]
