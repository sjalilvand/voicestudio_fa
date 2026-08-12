"""The panel's half of inbound mode: dial a node and hold the session open.

The mirror of ``transport/client.py``'s reconnect loop, from the other side.
This one dials, but it is still the *control plane*: it sends assignments and
receives results, and every frame it handles goes through the same
``WorkerServicer`` methods the outbound path uses. Only who opened the socket
changed.

Admission is the API key, in call metadata. Identity is still the node's
Ed25519 key: the first connection to a given node records its public key, and
every later one must present the same. The key admits, the keypair identifies —
conflating them would mean anyone who copied the key could impersonate the
machine to a panel that had already trusted it.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import socket
import ssl
from typing import Optional

import grpc

from worker import identity, registry, tls
from worker.inbound.connection_string import Connection
from worker.inbound.listener import KEY_METADATA_KEY
from worker.protocol.gen import worker_v1_pb2 as pb
from worker.protocol.gen import worker_v1_pb2_grpc as pb_grpc
from worker.transport.client import MAX_MESSAGE_BYTES, backoff_delay

logger = logging.getLogger(__name__)

_PUSH_CHUNK_BYTES = 1024 * 1024


def _fetch_pinned_certificate(
    connection: Connection, *, timeout: float = 10.0
) -> bytes:
    """Fetch the node certificate, then accept it only when its pin matches.

    The first TLS handshake is intentionally CA-agnostic because the node uses
    a self-signed certificate. The copied fingerprint is the trust anchor; the
    verified leaf is then the sole root trusted by the real gRPC channel.
    """
    context = tls.unverified_client_context()
    with socket.create_connection(
        (connection.host, connection.port), timeout=timeout
    ) as raw, context.wrap_socket(raw, server_hostname=connection.host) as secured:
        certificate_der = secured.getpeercert(binary_form=True)
    if not certificate_der or not tls.pin_matches(
        certificate_der, connection.fingerprint
    ):
        raise RuntimeError(
            "That GPU machine presented a different certificate fingerprint. "
            "Remove this connection and paste a newly created connection string."
        )
    return ssl.DER_cert_to_PEM_cert(certificate_der).encode("ascii")


class NodeConnection:
    """One panel→node session, reconnecting until told to stop."""

    def __init__(self, servicer, connection: Connection, *, label: str = "") -> None:
        self._servicer = servicer
        self._connection = connection
        self._label = label or connection.host
        self._outbox: asyncio.Queue[pb.ServerMessage] = asyncio.Queue()
        self._stub: Optional[pb_grpc.NodeServiceStub] = None
        self._worker_id = ""
        self._stop = asyncio.Event()
        self._last_error = ""

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def last_error(self) -> str:
        return self._last_error

    def _channel(self, certificate_pem: bytes) -> grpc.aio.Channel:
        credentials = grpc.ssl_channel_credentials(root_certificates=certificate_pem)
        return grpc.aio.secure_channel(
            self._connection.endpoint,
            credentials,
            options=[
                ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
                ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
                ("grpc.keepalive_time_ms", 25_000),
                ("grpc.keepalive_timeout_ms", 10_000),
                ("grpc.keepalive_permit_without_calls", 1),
            ],
        )

    async def run_forever(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                await self._connect_once()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                attempt += 1
                self._last_error = "Connection failed; check the backend log for details."
                delay = backoff_delay(attempt)
                logger.warning("Inbound worker connection failed; retry scheduled.")
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)

    async def stop(self) -> None:
        self._stop.set()

    async def _connect_once(self) -> None:
        # A fresh outbox per attempt. The queue used to be built once and
        # reused, so anything a dying session left behind became the NEXT
        # attach's first frame — the node then saw something other than the
        # registration it requires first, aborted the call, and the pair span
        # at full speed: on hardware this reached session epoch 2445 inside a
        # second, with the log reading "Locally aborted" over and over.
        self._outbox = asyncio.Queue()
        certificate_pem = await asyncio.to_thread(
            _fetch_pinned_certificate, self._connection
        )
        async with self._channel(certificate_pem) as channel:
            stub = pb_grpc.NodeServiceStub(channel)
            metadata = ((KEY_METADATA_KEY, self._connection.secret),)
            stream = stub.Attach(self._outbound(), metadata=metadata)

            # The node speaks first: it is the side with capabilities to
            # declare, whichever side dialled.
            first = await stream.read()
            if first == grpc.aio.EOF or first.WhichOneof("payload") != "register":
                raise RuntimeError(
                    "That machine answered, but not as a VoiceStudio GPU node."
                )

            response = self._register(first.register)
            if response.error.code:
                # A refusal here is a decision, not a blip: the node is a
                # different machine than the one this key was trusted for, or
                # its version cannot work with ours. Reconnecting cannot fix
                # either, so surface it rather than looping.
                raise RuntimeError(f"{response.error.code}: {response.error.message}")

            self._worker_id = response.worker_id
            self._stub = stub
            self._last_error = ""
            await self._outbox.put(pb.ServerMessage(registered=response))

            session = self._servicer.session_for(self._worker_id)
            if session is None:
                raise RuntimeError("the session went away before the stream opened")

            pump = asyncio.create_task(self._pump_outbound(session))
            try:
                await self._servicer.run_inbound_stream(session, _Frames(stream), self)
            finally:
                pump.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pump
                self._stub = None

    def _register(self, request: pb.RegisterRequest) -> pb.RegisterResponse:
        """Trust on first sight, then require the same key forever after.

        Pasting the connection string is the consent — the user went to the
        machine, generated a key and brought it here, which is a stronger
        statement of intent than any dialog this could show. What it is *not*
        is a licence for a different machine to answer at that address later,
        which is why the key is bound on first contact.
        """
        public_key = bytes(request.public_key)
        if len(public_key) != 32:
            return self._servicer._refuse(
                "AUTH_FAILED", "That machine sent no usable identity."
            )
        key_id = identity.key_id_for(public_key)
        if registry.is_revoked(key_id):
            return self._servicer._refuse(
                "AUTH_FAILED",
                "This GPU machine was removed from this app. Add it again to use it.",
            )

        known = registry.get_by_key_id(key_id)
        if known is None:
            worker = registry.enroll_worker(
                name=request.host.hostname or self._label,
                public_key=public_key,
                endpoint=self._connection.endpoint,
                consent_granted=True,
            )
        else:
            worker = registry.authenticate(
                key_id=key_id,
                public_key=public_key,
                challenge=bytes(request.challenge),
                signature=bytes(request.challenge_signature),
                nonce=bytes(request.nonce),
                session_epoch=request.envelope.sequence,
            )
            if worker is None and self._proves_key_possession(request, known):
                # The node holds the right private key but signed over a
                # different worker id than this panel recorded — which is what
                # happens whenever a node meets a panel it has enrolled with
                # before but whose id it no longer has (a re-issued key, a
                # reset data dir). Possession of the key is the security
                # property; the id is only binding, and refusing here would
                # strand a machine that is provably the right one with no way
                # back except deleting it from both sides.
                logger.info(
                    "Re-adopting GPU machine %s: it proved its key but had lost its id here",
                    known.name,
                )
                worker = known
            if worker is None:
                return self._servicer._refuse(
                    "AUTH_FAILED",
                    "That machine could not prove it is the one this key was added for.",
                )

        return self._servicer.register_inbound(
            worker, request, address=self._connection.endpoint
        )

    @staticmethod
    def _proves_key_possession(request: pb.RegisterRequest, known) -> bool:
        """Does this signature verify against the id the NODE thinks it has?

        Deliberately narrow: the public key must already be the one enrolled
        for this worker, so this can only ever re-adopt a machine this panel
        already trusts. It cannot admit a new key.
        """
        public_key = bytes(request.public_key)
        if known is None or known.revoked or known.public_key != public_key:
            return False
        message = identity.challenge_message(
            challenge=bytes(request.challenge),
            worker_id=request.worker_id,
            session_epoch=request.envelope.sequence,
            nonce=bytes(request.nonce),
        )
        return identity.verify_signature(
            public_key, message, bytes(request.challenge_signature)
        )

    async def _outbound(self):
        while True:
            yield await self._outbox.get()

    async def _pump_outbound(self, session) -> None:
        """Move the servicer's per-session outbox onto the dialled stream.

        Outbound mode writes straight to the gRPC context; here the frames have
        to cross into the request generator instead, because this side is the
        caller.
        """
        while True:
            await self._outbox.put(await session.outbox.get())

    # ── Artifacts ─────────────────────────────────────────────────────────

    async def push_input(self, ref: pb.ArtifactRef, path: str) -> pb.ArtifactRef:
        """Send one task input up to the node before the assignment goes out.

        Pushed rather than pulled because the node cannot call us. Ordering
        matters: the executor asks for its inputs as soon as it starts, so an
        assignment that overtakes its own inputs fails on a file that is merely
        late.
        """
        stub = self._stub
        if stub is None:
            raise RuntimeError("that GPU machine is not connected")

        size = os.path.getsize(path)
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            digest.update(handle.read())

        declared = pb.ArtifactRef()
        declared.CopyFrom(ref)
        declared.size_bytes = size
        declared.sha256 = digest.hexdigest()
        if not declared.filename:
            declared.filename = os.path.basename(path)

        async def chunks():
            offset = 0
            with open(path, "rb") as handle:
                while True:
                    data = handle.read(_PUSH_CHUNK_BYTES)
                    if not data:
                        break
                    offset += len(data)
                    yield pb.ArtifactChunk(
                        ref=declared,
                        offset=offset - len(data),
                        data=data,
                        last=offset >= size,
                    )

        ack = await stub.PushInput(
            chunks(), metadata=((KEY_METADATA_KEY, self._connection.secret),)
        )
        if not ack.committed:
            raise RuntimeError(
                ack.error.message or "that GPU machine did not accept the input"
            )
        return declared

    async def fetch_result(
        self, ref: pb.ArtifactRef, destination: str, *, max_bytes: Optional[int] = None
    ) -> None:
        """Pull a finished result down, verifying it against its declared hash."""
        stub = self._stub
        if stub is None:
            raise RuntimeError("that GPU machine is not connected")

        request = pb.ArtifactRef()
        request.CopyFrom(ref)
        digest = hashlib.sha256()
        offset = 0
        complete = False
        try:
            with open(destination, "wb") as handle:
                async for chunk in stub.FetchResult(
                    request, metadata=((KEY_METADATA_KEY, self._connection.secret),)
                ):
                    if int(chunk.offset) != offset:
                        raise RuntimeError(
                            f"result offset {chunk.offset} did not match {offset} bytes received"
                        )
                    if max_bytes is not None and offset + len(chunk.data) > max_bytes:
                        raise RuntimeError(
                            "the result is larger than the control plane accepts"
                        )
                    handle.write(chunk.data)
                    digest.update(chunk.data)
                    offset += len(chunk.data)
                    if chunk.last:
                        complete = True
                        break
        except Exception:
            with contextlib.suppress(OSError):
                os.remove(destination)
            raise

        # A truncated file that is renamed into place and called done is the
        # exact failure the upload path was hardened against; the pull
        # direction gets the same treatment.
        if not complete:
            with contextlib.suppress(OSError):
                os.remove(destination)
            raise RuntimeError("the result ended before its final chunk")
        if ref.sha256 and digest.hexdigest() != ref.sha256:
            with contextlib.suppress(OSError):
                os.remove(destination)
            raise RuntimeError(
                "the result did not match the checksum that machine declared"
            )


class _Frames:
    """Adapts a gRPC client stream to the ``async for`` the read loop expects."""

    def __init__(self, stream) -> None:
        self._stream = stream

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self._stream.read()
        if message == grpc.aio.EOF:
            raise StopAsyncIteration
        return message
