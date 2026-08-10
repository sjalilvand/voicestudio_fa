"""Worker-side gRPC client.

Runs on the machine with the GPU. Its job is to stay connected, report what it
can do honestly, and execute what it is given.

Two things here are load-bearing:

**Certificate pinning.** The control plane is a desktop with a self-signed
certificate, so the enrollment token's fingerprint is the trust anchor. The
pinned certificate is supplied as the *only* trusted root, which means an
attacker on the same network cannot substitute their own — and there is no
flag to turn that off.

**Reconnect with backoff and jitter.** Home networks drop. A worker that
reconnects instantly and in lockstep with its siblings turns a thirty-second
outage into a thundering herd, so the delay grows and is jittered. Crucially
the worker keeps any unacknowledged result across the reconnect and redelivers
it: that is the half of at-least-once delivery that lives on this side.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import random
import socket
import sys
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

import grpc

from worker import errors as worker_errors
from worker import identity
from worker.errors import WorkerError
from worker.identity import EnrollmentToken, WorkerKeypair
from worker.protocol.gen import worker_v1_pb2 as pb
from worker.protocol.gen import worker_v1_pb2_grpc as pb_grpc
from worker.transport import codec
from worker.transport.server import PROTOCOL_VERSION, SESSION_METADATA_KEY

logger = logging.getLogger("omnivoice.worker")

_BASE_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 60.0
_HEARTBEAT_SECONDS = 20.0


def backoff_delay(attempt: int, *, jitter: Optional[Callable[[], float]] = None) -> float:
    """Exponential backoff with full jitter, bounded.

    Full jitter rather than a fixed fraction: with several workers behind the
    same router, a deterministic delay reconnects them all in the same instant
    and the control plane sees a spike exactly when it is least able to absorb
    one.
    """
    ceiling = min(_MAX_BACKOFF_SECONDS, _BASE_BACKOFF_SECONDS * (2 ** max(0, attempt - 1)))
    roll = jitter() if jitter is not None else random.random()
    return ceiling * roll


@dataclass
class PendingResult:
    """A finished result the server has not acknowledged yet.

    Held until RESULT_ACK arrives, across reconnects. Dropping it early is how
    a completed forty-minute dub disappears with no error anywhere.
    """

    ref: pb.TaskRef
    result_json: str = ""
    inline_payload: bytes = b""
    usage: Optional[pb.UsageReport] = None


@dataclass
class WorkerConfig:
    """Everything the worker needs to reach and prove itself to a server."""

    endpoint: str
    cert_fingerprint: str
    certificate_pem: bytes
    keypair: WorkerKeypair
    worker_id: str = ""
    enrollment_token: str = ""
    max_concurrent_tasks: int = 1
    capabilities: list[dict] = field(default_factory=list)
    host: dict = field(default_factory=dict)


def describe_host() -> dict:
    """Static facts about this machine, for registration."""
    try:
        from core.version import APP_VERSION  # noqa: PLC0415
    except Exception:
        APP_VERSION = ""
    return {
        "hostname": socket.gethostname(),
        "os": {"darwin": "darwin", "win32": "windows"}.get(sys.platform, "linux"),
        "arch": platform.machine(),
        "worker_version": APP_VERSION,
        "cpu_count": os.cpu_count() or 0,
    }


class WorkerClient:
    """Maintains one worker's connection to a control plane."""

    def __init__(
        self,
        config: WorkerConfig,
        *,
        execute: Callable[[pb.TaskAssignment], Awaitable[dict]],
        cancel: Optional[Callable[[str], Awaitable[None]]] = None,
        capability_probe: Optional[Callable[[], list[dict]]] = None,
    ) -> None:
        self.config = config
        self._execute = execute
        self._cancel = cancel
        self._capability_probe = capability_probe
        self._outbox: asyncio.Queue[pb.WorkerMessage] = asyncio.Queue()
        self._pending: dict[str, PendingResult] = {}
        self._running: dict[str, asyncio.Task] = {}
        self._epoch = 0
        self._session_token = ""
        self._stop = asyncio.Event()

    # ── Connection ────────────────────────────────────────────────────────

    def _channel(self) -> grpc.aio.Channel:
        """A channel that trusts exactly one certificate — the pinned one."""
        credentials = grpc.ssl_channel_credentials(root_certificates=self.config.certificate_pem)
        return grpc.aio.secure_channel(
            self.config.endpoint,
            credentials,
            options=[
                ("grpc.max_receive_message_length", 8 * 1024 * 1024),
                ("grpc.max_send_message_length", 8 * 1024 * 1024),
                ("grpc.keepalive_time_ms", 25_000),
                ("grpc.keepalive_timeout_ms", 10_000),
                ("grpc.keepalive_permit_without_calls", 1),
            ],
        )

    async def run_forever(self) -> None:
        """Connect, serve, and reconnect until stopped."""
        attempt = 0
        while not self._stop.is_set():
            try:
                await self._connect_once()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                delay = backoff_delay(attempt)
                logger.warning(
                    "Worker connection failed (%s). Reconnecting in %.1fs.", exc, delay
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass

    async def stop(self) -> None:
        self._stop.set()

    async def _connect_once(self) -> None:
        async with self._channel() as channel:
            stub = pb_grpc.WorkerServiceStub(channel)
            response = await self._register(stub)
            if response.error.code:
                # An authentication or version refusal is not something a
                # retry loop fixes; say so rather than reconnecting forever.
                raise RuntimeError(f"{response.error.code}: {response.error.message}")

            self._epoch = response.session_epoch
            self._session_token = response.session_token
            self.config.worker_id = response.worker_id
            # The token is spent; every later connection proves key possession.
            self.config.enrollment_token = ""

            authoritative = {ref.attempt_id for ref in response.authoritative_in_flight}
            await self._cancel_zombies(authoritative)
            await self._redeliver_pending()

            metadata = ((SESSION_METADATA_KEY, self._session_token),)
            stream = stub.Control(self._outbound(), metadata=metadata)
            heartbeat = asyncio.create_task(
                self._heartbeat_loop(response.heartbeat_interval_seconds or _HEARTBEAT_SECONDS)
            )
            try:
                async for message in stream:
                    await self._on_server_message(message)
            finally:
                heartbeat.cancel()

    async def _register(self, stub) -> pb.RegisterResponse:
        challenge = identity.new_challenge()
        nonce = identity.new_challenge()
        signature = self.config.keypair.sign(
            identity.challenge_message(
                challenge=challenge,
                worker_id=self.config.worker_id,
                session_epoch=self._epoch,
                nonce=nonce,
            )
        )
        capabilities = (
            self._capability_probe() if self._capability_probe else self.config.capabilities
        )
        return await stub.Register(
            pb.RegisterRequest(
                envelope=pb.Envelope(sequence=self._epoch),
                protocol_version_min=PROTOCOL_VERSION,
                protocol_version_max=PROTOCOL_VERSION,
                enrollment_token=self.config.enrollment_token,
                worker_id=self.config.worker_id,
                public_key=self.config.keypair.public_bytes(),
                challenge=challenge,
                challenge_signature=signature,
                nonce=nonce,
                key_id=self.config.keypair.key_id,
                host=codec.host_to_pb(self.config.host or describe_host()),
                capabilities=[codec.capability_to_pb(c) for c in capabilities],
                max_concurrent_tasks=self.config.max_concurrent_tasks,
                in_flight=[
                    codec.task_ref(t.split("/")[0], t.split("/")[1], self._epoch)
                    for t in self._running
                ],
                completed_unacked=[p.ref for p in self._pending.values()],
            )
        )

    # ── Outbound ──────────────────────────────────────────────────────────

    async def _outbound(self):
        while True:
            message = await self._outbox.get()
            yield message

    async def _send(self, message: pb.WorkerMessage) -> None:
        await self._outbox.put(message)

    async def _heartbeat_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await self._send(
                pb.WorkerMessage(
                    heartbeat=pb.Heartbeat(
                        active_tasks=len(self._running),
                        available_slots=max(
                            0, self.config.max_concurrent_tasks - len(self._running)
                        ),
                        resident_models=self._resident_models(),
                    )
                )
            )

    def _resident_models(self) -> list[str]:
        return [
            f"{c.get('engine')}:{c.get('model_id')}"
            for c in (self.config.capabilities or [])
            if c.get("resident")
        ]

    async def _redeliver_pending(self) -> None:
        """Re-send anything the server never acknowledged."""
        for pending in list(self._pending.values()):
            logger.info("Redelivering unacknowledged result for task %s", pending.ref.task_id)
            await self._send(
                pb.WorkerMessage(
                    result=pb.TaskResult(
                        ref=pending.ref,
                        result_json=pending.result_json,
                        inline_payload=pending.inline_payload,
                    )
                )
            )

    async def _cancel_zombies(self, authoritative: set[str]) -> None:
        """Stop work the control plane no longer believes in."""
        for key in list(self._running):
            attempt_id = key.split("/")[1]
            if attempt_id not in authoritative:
                logger.info("Cancelling task %s — the server no longer expects it", key)
                await self._abandon(key)

    async def _abandon(self, key: str) -> None:
        task = self._running.pop(key, None)
        if task is not None:
            task.cancel()
        if self._cancel is not None:
            await self._cancel(key.split("/")[0])

    # ── Inbound ───────────────────────────────────────────────────────────

    async def _on_server_message(self, message: pb.ServerMessage) -> None:
        kind = message.WhichOneof("payload")
        if kind == "assignment":
            await self._on_assignment(message.assignment)
        elif kind == "cancel":
            await self._abandon(self._key(message.cancel.ref))
            await self._send(
                pb.WorkerMessage(cancel_ack=pb.TaskCancelAck(ref=message.cancel.ref))
            )
        elif kind == "result_ack":
            # Only now is it safe to forget the result.
            self._pending.pop(self._key(message.result_ack.ref), None)
        elif kind == "config":
            if message.config.max_concurrent_tasks:
                self.config.max_concurrent_tasks = message.config.max_concurrent_tasks
        elif kind == "ping":
            pass
        elif kind == "drain":
            self._stop.set()
        elif kind == "shutdown":
            self._stop.set()

    @staticmethod
    def _key(ref: pb.TaskRef) -> str:
        return f"{ref.task_id}/{ref.attempt_id}"

    async def _on_assignment(self, assignment: pb.TaskAssignment) -> None:
        key = self._key(assignment.ref)
        if len(self._running) >= self.config.max_concurrent_tasks:
            # Declining because we are full is normal and penalty-free; the
            # scheduler's view of our capacity is only ever advisory.
            await self._send(
                pb.WorkerMessage(
                    rejected=pb.TaskRejected(
                        ref=assignment.ref,
                        error=pb.Error(
                            error_class=pb.ERROR_CLASS_CAPACITY,
                            code="WORKER_AT_CAPACITY",
                            message="The worker has no free slot.",
                        ),
                    )
                )
            )
            return
        await self._send(pb.WorkerMessage(accepted=pb.TaskAccepted(ref=assignment.ref)))
        self._running[key] = asyncio.create_task(self._run(assignment))

    async def _run(self, assignment: pb.TaskAssignment) -> None:
        key = self._key(assignment.ref)
        try:
            await self._send(pb.WorkerMessage(started=pb.TaskStarted(ref=assignment.ref)))
            result = await self._execute(assignment)
            pending = PendingResult(
                ref=assignment.ref,
                result_json=json.dumps(result.get("meta", {})),
                inline_payload=result.get("payload", b"") or b"",
            )
            # Recorded BEFORE sending: if the connection dies mid-send we must
            # still know to redeliver.
            self._pending[key] = pending
            await self._send(
                pb.WorkerMessage(
                    result=pb.TaskResult(
                        ref=pending.ref,
                        result_json=pending.result_json,
                        inline_payload=pending.inline_payload,
                    )
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # An executor that already classified the failure knows more than
            # a generic exception sniff can recover — keep its verdict, so a
            # "this input is bad" does not get retried around the whole fleet.
            from worker.executor import TaskFailure  # noqa: PLC0415

            failure: WorkerError = (
                exc.error if isinstance(exc, TaskFailure) else worker_errors.from_exception(exc)
            )
            await self._send(
                pb.WorkerMessage(
                    failed=pb.TaskFailed(
                        ref=assignment.ref, error=codec.error_to_pb(failure)
                    )
                )
            )
        finally:
            self._running.pop(key, None)


def verify_pin(certificate_pem: bytes, expected_fingerprint: str) -> bool:
    """Check a server certificate against the fingerprint from the token."""
    from cryptography import x509  # noqa: PLC0415
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

    from worker.tls import pin_matches  # noqa: PLC0415

    certificate = x509.load_pem_x509_certificate(certificate_pem)
    return pin_matches(
        certificate.public_bytes(serialization.Encoding.DER), expected_fingerprint
    )


def config_from_token(
    token_text: str, *, keypair: WorkerKeypair, certificate_pem: bytes
) -> WorkerConfig:
    """Build a worker configuration from a pasted enrollment token.

    Refuses outright if the presented certificate does not match the token's
    fingerprint — that mismatch is exactly what pinning exists to catch, and
    there is no override.
    """
    token: EnrollmentToken = EnrollmentToken.decode(token_text)
    if token.expired():
        raise ValueError("This enrollment token has expired. Generate a new one.")
    if not verify_pin(certificate_pem, token.cert_fingerprint):
        raise ValueError(
            "The server's certificate does not match this enrollment token. "
            "Do not continue — generate a fresh token on the control plane."
        )
    return WorkerConfig(
        endpoint=token.endpoint,
        cert_fingerprint=token.cert_fingerprint,
        certificate_pem=certificate_pem,
        keypair=keypair,
        enrollment_token=token_text,
    )


__all__ = [
    "PendingResult",
    "WorkerClient",
    "WorkerConfig",
    "backoff_delay",
    "config_from_token",
    "describe_host",
    "verify_pin",
]
