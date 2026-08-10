"""Worker mode — the other half of the feature.

A worker is the ordinary backend with this agent running alongside it. That is
the whole point of not writing a slim agent: the engines, sidecar venvs, model
downloads, and VRAM budgeting the executor needs are already there.

The interesting problem here is bootstrapping trust. The control plane has a
self-signed certificate, so the worker has nothing to validate it against —
except the fingerprint baked into the enrollment token. So on first contact the
worker fetches the certificate the server presents, checks it against that
fingerprint, and only then uses it as the *sole* trusted root for every later
connection. Trust on first use, with the token as the anchor that makes the
"first use" safe.

If the fingerprint does not match, the agent stops. It does not warn and
continue: a mismatch is precisely the attack pinning exists to catch.
"""
from __future__ import annotations

import asyncio
import logging
import os
import ssl
from typing import Optional

logger = logging.getLogger("omnivoice.worker")


def worker_mode_enabled() -> bool:
    return (os.environ.get("OMNIVOICE_WORKER_MODE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _paths() -> dict[str, str]:
    from worker.service import paths  # noqa: PLC0415

    locations = paths()
    locations["pinned_cert"] = os.path.join(locations["root"], "control-plane.pinned.crt")
    return locations


def fetch_server_certificate(endpoint: str, *, timeout: float = 10.0) -> bytes:
    """Retrieve the certificate the control plane presents, unvalidated.

    Unvalidated on purpose and safe only because the caller immediately checks
    it against the token's fingerprint — this is the fetch half of pin-on-first-
    use, not a trust decision.
    """
    host, _, port = endpoint.rpartition(":")
    if not host:
        raise ValueError(f"Endpoint must be host:port — got {endpoint!r}")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with ssl.create_connection((host, int(port)), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise ConnectionError("The control plane presented no certificate.")
    return ssl.DER_cert_to_PEM_cert(der).encode("ascii")


def pin_certificate(token_text: str, *, cert_path: Optional[str] = None) -> tuple[str, bytes]:
    """Resolve a token into (endpoint, trusted certificate), pinning on first use.

    Raises ``ValueError`` when the presented certificate does not match the
    token. There is deliberately no override.
    """
    from worker.identity import EnrollmentToken  # noqa: PLC0415
    from worker.transport.client import verify_pin  # noqa: PLC0415

    token = EnrollmentToken.decode(token_text)
    if token.expired():
        raise ValueError("This enrollment token has expired. Generate a new one.")

    certificate = fetch_server_certificate(token.endpoint)
    if not verify_pin(certificate, token.cert_fingerprint):
        raise ValueError(
            "The control plane's certificate does not match this enrollment token. "
            "Stop — this is what the token's fingerprint exists to catch. Generate a "
            "fresh token on the control plane and try again."
        )

    path = cert_path or _paths()["pinned_cert"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(certificate)
    return token.endpoint, certificate


class WorkerAgent:
    """Keeps this machine connected to a control plane and running its work."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._client = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, *, token_text: str = "", endpoint: str = "") -> None:
        from worker import capabilities  # noqa: PLC0415
        from worker.executor import TaskExecutor  # noqa: PLC0415
        from worker.identity import load_or_create_worker_key  # noqa: PLC0415
        from worker.transport.client import (  # noqa: PLC0415
            WorkerClient,
            WorkerConfig,
            describe_host,
        )

        if self.running:
            return

        locations = _paths()
        os.makedirs(locations["root"], exist_ok=True)
        # Generated once and never transmitted; this is the worker's identity
        # for the life of the machine.
        keypair = load_or_create_worker_key(locations["worker_key"])

        token_text = token_text or (os.environ.get("OMNIVOICE_WORKER_TOKEN") or "").strip()
        if token_text:
            endpoint, certificate = await asyncio.to_thread(pin_certificate, token_text)
        else:
            # Already enrolled: reuse the certificate pinned at join time.
            try:
                with open(locations["pinned_cert"], "rb") as fh:
                    certificate = fh.read()
            except (FileNotFoundError, PermissionError) as exc:
                raise RuntimeError(
                    "This machine has not been enrolled yet. Generate a token on the "
                    "control plane (Settings → Sharing → Remote workers) and start with "
                    "OMNIVOICE_WORKER_TOKEN set."
                ) from exc
            endpoint = endpoint or (os.environ.get("OMNIVOICE_WORKER_ENDPOINT") or "").strip()
            if not endpoint:
                raise RuntimeError(
                    "Set OMNIVOICE_WORKER_ENDPOINT to the control plane's host:port, or "
                    "start with a fresh OMNIVOICE_WORKER_TOKEN."
                )

        discovered = capabilities.discover()
        host = describe_host()
        host["gpus"] = capabilities.describe_gpus()

        config = WorkerConfig(
            endpoint=endpoint,
            cert_fingerprint="",
            certificate_pem=certificate,
            keypair=keypair,
            enrollment_token=token_text,
            max_concurrent_tasks=capabilities.max_concurrent_tasks(discovered),
            capabilities=discovered,
            host=host,
        )
        executor = TaskExecutor()
        self._client = WorkerClient(
            config,
            execute=executor.execute,
            # Re-probed on every reconnect so a model loaded (or evicted) since
            # the last connection is reported honestly rather than from a
            # snapshot taken at startup.
            capability_probe=capabilities.discover,
        )
        self._task = asyncio.create_task(self._client.run_forever(), name="worker-agent")
        logger.info(
            "Worker agent connecting to %s with %d engine(s)", endpoint, len(discovered)
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.stop()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self._client = None


agent = WorkerAgent()


async def start_if_worker_mode() -> None:
    """Called from the app lifespan on the worker machine.

    Never fatal: a machine that cannot reach its control plane is still a
    perfectly good OmniVoice install for the person sitting at it.
    """
    if not worker_mode_enabled():
        return
    try:
        await agent.start()
    except Exception:
        logger.exception("Worker agent failed to start (the app continues normally)")


async def stop() -> None:
    try:
        await agent.stop()
    except Exception:
        logger.exception("Worker agent failed to stop cleanly")


__all__ = [
    "WorkerAgent",
    "agent",
    "fetch_server_certificate",
    "pin_certificate",
    "start_if_worker_mode",
    "stop",
    "worker_mode_enabled",
]
