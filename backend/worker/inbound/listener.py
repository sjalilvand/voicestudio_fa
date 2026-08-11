"""The node's inbound listener: a gRPC server hosting NodeService.

Off by default. Enabling it is the consent surface — there is no per-job
approval prompt, because a prompt per job makes a shared GPU unusable and
trains people to click yes. What replaces it is visibility: every attach,
refusal and disconnect is in the connection log, and any session can be kicked.

Binds to 127.0.0.1 unless the user separately and explicitly widens it. That
default is nearly useless on its own, which is the point: reaching a node from
another machine should be a decision someone made, not a side effect of turning
on a feature.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import uuid
from typing import Callable, Optional

import grpc

from worker.inbound.artifacts import ArtifactStore
from worker.inbound.connection_log import ConnectionLog
from worker.inbound.keys import KeyStore
from worker.protocol.gen import worker_v1_pb2 as pb
from worker.protocol.gen import worker_v1_pb2_grpc as pb_grpc
from worker.transport.client import MAX_MESSAGE_BYTES, WorkerClient

logger = logging.getLogger(__name__)

# The panel presents its key here. Lower-case because gRPC normalises metadata
# keys and a mixed-case constant silently never matches.
KEY_METADATA_KEY = "x-omnivoice-node-key"

DEFAULT_PORT = 7444
DEFAULT_BIND = "127.0.0.1"

_FETCH_CHUNK_BYTES = 1024 * 1024


def _peer_of(context) -> str:
    """A loggable source address. gRPC formats these as ipv4:1.2.3.4:5678."""
    try:
        raw = context.peer() or ""
    except Exception:
        return ""
    for prefix in ("ipv4:", "ipv6:"):
        if raw.startswith(prefix):
            return raw[len(prefix) :]
    return raw


class NodeServicer(pb_grpc.NodeServiceServicer):
    """Serves one node to any number of panels."""

    def __init__(
        self,
        *,
        keys: KeyStore,
        log: ConnectionLog,
        artifacts: ArtifactStore,
        client_factory: Callable[[ArtifactStore, str], WorkerClient],
    ) -> None:
        self._keys = keys
        self._log = log
        self._artifacts = artifacts
        self._client_factory = client_factory
        # Live clients, one per attached panel. Kept so a freed engine can be
        # re-advertised to everyone rather than only to whoever asks next.
        self._clients: set = set()

    async def refresh_all(self) -> None:
        for client in list(self._clients):
            try:
                await client.refresh_capabilities()
            except Exception:
                logger.debug("Could not refresh capabilities for a panel", exc_info=True)

    # ── Admission ─────────────────────────────────────────────────────────

    def _authenticate(self, context) -> Optional[tuple[str, str]]:
        """Return (key_id, label) or None, logging the refusal either way."""
        peer = _peer_of(context)
        if self._keys.locked_out(peer):
            self._log.rejected(peer=peer, detail="too many failed keys")
            return None
        metadata = {k.lower(): v for k, v in (context.invocation_metadata() or ())}
        secret = metadata.get(KEY_METADATA_KEY, "")
        key = self._keys.authenticate(secret, peer=peer)
        if key is not None and self._log.cooling_down(key.key_id):
            self._log.rejected(peer=peer, detail="recently disconnected by the owner")
            return None
        if key is None:
            self._log.rejected(
                peer=peer, detail="no key" if not secret else "key not recognised"
            )
            return None
        return key.key_id, key.label

    # ── Attach ────────────────────────────────────────────────────────────

    async def Attach(self, request_iterator, context):
        admitted = self._authenticate(context)
        if admitted is None:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "This GPU machine did not recognise that key.",
            )
            return
        key_id, label = admitted

        session_id = uuid.uuid4().hex
        peer = _peer_of(context)
        self._log.opened(session_id=session_id, key_id=key_id, label=label, peer=peer)
        # Built per key, not per node: each panel keeps its own registry, so
        # the same machine has a different worker id to each of them, and the
        # node signs its challenge over that id. Handing every panel the same
        # client would make the signature match at most one of them.
        client = self._client_factory(self._artifacts, key_id)
        self._clients.add(client)
        reader: Optional[asyncio.Task] = None
        heartbeat: Optional[asyncio.Task] = None
        try:
            # The node speaks first even though the panel dialled: it is still
            # the side with capabilities to declare, and the panel cannot
            # schedule anything until it knows them.
            yield pb.WorkerMessage(register=client.build_register_request())

            first = await _next_frame(request_iterator)
            if first is None or first.WhichOneof("payload") != "registered":
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Expected the control plane to answer with a registration.",
                )
                return
            await client.accept_registration(first.registered)

            heartbeat = client.start_heartbeat(first.registered)
            reader = asyncio.create_task(
                self._pump_incoming(client, request_iterator, session_id)
            )
            while True:
                if self._log.disconnect_requested(session_id):
                    yield pb.WorkerMessage(
                        goodbye=pb.WorkerGoodbye(
                            reason="The owner of this GPU machine ended the session."
                        )
                    )
                    return
                # Bounded so a kick lands within a second even on an idle
                # session, where nothing else would wake this loop.
                try:
                    frame = await asyncio.wait_for(client.next_outbound(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                yield frame
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Inbound session from %s ended: %s", peer or "a panel", exc)
        finally:
            for task in (reader, heartbeat):
                if task is None:
                    continue
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            self._clients.discard(client)
            await client.stop()
            self._log.closed(session_id)

    async def _pump_incoming(self, client: WorkerClient, request_iterator, session_id: str) -> None:
        async for message in request_iterator:
            kind = message.WhichOneof("payload")
            if kind == "assignment":
                self._log.task_started(session_id)
            if kind == "registered":
                # A second registration on a live stream is a control plane
                # bug, not a re-handshake. Ignoring it is safer than adopting
                # a new epoch mid-session and fencing the work in flight.
                logger.warning("Ignoring a repeated registration on a live session")
                continue
            await client.handle_server_message(message)

    # ── Artifacts ─────────────────────────────────────────────────────────

    async def FetchResult(self, request, context):
        if self._authenticate(context) is None:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "This GPU machine did not recognise that key.",
            )
            return
        staged = self._artifacts.open_result(request.artifact_id)
        if staged is None:
            await context.abort(
                grpc.StatusCode.NOT_FOUND, "That result is no longer on this machine."
            )
            return

        # Always from the start. `size_bytes` on the incoming ref is the
        # artifact's TOTAL size, not a resume point — reading it as one seeks
        # straight to EOF, yields no chunks, and the fetch fails with "the
        # result ended before its final chunk" while the render sits complete
        # on disk. ArtifactRef carries no resume field, so resumption needs a
        # protocol addition rather than a reinterpreted one.
        offset = 0
        try:
            with open(staged.path, "rb") as handle:
                while True:
                    data = handle.read(_FETCH_CHUNK_BYTES)
                    if not data:
                        break
                    chunk = pb.ResultChunk(
                        ref=pb.ArtifactRef(
                            artifact_id=request.artifact_id,
                            task_id=request.task_id,
                            attempt_id=request.attempt_id,
                            filename=os.path.basename(staged.path),
                            size_bytes=staged.size_bytes,
                            sha256=staged.sha256,
                        ),
                        offset=offset,
                        data=data,
                    )
                    offset += len(data)
                    chunk.last = offset >= staged.size_bytes
                    yield chunk
        except OSError as exc:
            await context.abort(grpc.StatusCode.INTERNAL, f"Could not read the result: {exc}")
            return
        # Dropped only after the last chunk left this process. A panel that
        # dies mid-fetch can ask again; the stale sweep is what eventually
        # reclaims it.
        self._artifacts.result_fetched(request.artifact_id)

    async def PushInput(self, request_iterator, context):
        if self._authenticate(context) is None:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "This GPU machine did not recognise that key.",
            )
            return pb.ArtifactAck()

        ref: Optional[pb.ArtifactRef] = None
        path = ""
        handle = None
        digest = hashlib.sha256()
        received = 0
        committed = False
        try:
            async for chunk in request_iterator:
                if ref is None:
                    ref = chunk.ref
                    path = self._artifacts.begin_input(ref)
                    handle = open(path, "wb")
                if int(chunk.offset) != received:
                    return pb.ArtifactAck(
                        artifact_id=ref.artifact_id if ref else "",
                        bytes_received=received,
                        error=pb.Error(
                            code="OFFSET_MISMATCH",
                            message=f"expected offset {received}, got {chunk.offset}",
                        ),
                    )
                handle.write(chunk.data)
                digest.update(chunk.data)
                received += len(chunk.data)
                if chunk.last:
                    committed = True
                    break
        except Exception as exc:
            return pb.ArtifactAck(
                artifact_id=ref.artifact_id if ref else "",
                bytes_received=received,
                error=pb.Error(code="INPUT_WRITE_FAILED", message=str(exc)),
            )
        finally:
            if handle is not None:
                handle.close()

        if ref is None or not committed:
            # An iterator that simply ends is a truncated transfer, not a
            # finished one. Committing here is exactly the bug that let a
            # short upload be renamed into place and called done.
            if path:
                with contextlib.suppress(OSError):
                    os.remove(path)
            return pb.ArtifactAck(
                bytes_received=received,
                error=pb.Error(
                    code="INPUT_INCOMPLETE",
                    message="the input ended before its final chunk",
                ),
            )

        actual = digest.hexdigest()
        if ref.sha256 and actual != ref.sha256:
            with contextlib.suppress(OSError):
                os.remove(path)
            return pb.ArtifactAck(
                artifact_id=ref.artifact_id,
                bytes_received=received,
                error=pb.Error(
                    code="INPUT_CHECKSUM_MISMATCH",
                    message="the input did not match the checksum the control plane declared",
                ),
            )

        self._artifacts.commit_input(ref, path, actual, received)
        return pb.ArtifactAck(
            artifact_id=ref.artifact_id, bytes_received=received, committed=True
        )


async def _next_frame(request_iterator):
    try:
        return await request_iterator.__anext__()
    except StopAsyncIteration:
        return None


class NodeListener:
    """Owns the gRPC server. Started only when the user turns inbound on."""

    def __init__(
        self,
        *,
        keys: KeyStore,
        log: ConnectionLog,
        artifacts: ArtifactStore,
        client_factory: Callable[[ArtifactStore, str], WorkerClient],
    ) -> None:
        self._servicer = NodeServicer(
            keys=keys, log=log, artifacts=artifacts, client_factory=client_factory
        )
        self._artifacts = artifacts
        self._server: Optional[grpc.aio.Server] = None
        self._bound_port = 0

    async def refresh_all(self) -> None:
        """Re-advertise capabilities to every attached panel."""
        await self._servicer.refresh_all()

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int:
        """The port actually bound, which is not always the one requested."""
        return self._bound_port

    async def start(self, *, host: str = DEFAULT_BIND, port: int = DEFAULT_PORT) -> int:
        if self._server is not None:
            return self._bound_port
        server = grpc.aio.server(
            options=[
                ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
                ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
                # A panel's channel pings on an idle Attach stream exactly as a
                # worker's does outbound. Without these the server answers
                # too_many_pings and evicts the healthy panels it was waiting
                # for — the same eviction that cost this feature a day when the
                # control plane did it.
                ("grpc.keepalive_permit_without_calls", 1),
                ("grpc.http2.min_ping_interval_without_data_ms", 20_000),
                ("grpc.http2.max_pings_without_data", 0),
            ]
        )
        pb_grpc.add_NodeServiceServicer_to_server(self._servicer, server)
        # Plaintext by design; see docs/adr/inbound-node-mode.md. The API
        # key is what admits a panel, and it is not confidential against
        # anyone who can read this LAN segment.
        bind = f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"
        bound = server.add_insecure_port(bind)
        if not bound:
            raise RuntimeError(
                f"Could not listen on {bind}. Another program may already be using that port."
            )
        await server.start()
        self._server = server
        self._bound_port = bound
        logger.info("Inbound node listener accepting connections on %s", bind)
        return bound

    async def stop(self) -> None:
        server, self._server = self._server, None
        self._bound_port = 0
        if server is not None:
            await server.stop(grace=1.0)
        self._artifacts.purge()
