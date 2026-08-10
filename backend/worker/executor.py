"""Runs assigned tasks on a worker, using the engines already installed there.

A worker is the ordinary backend in worker mode, not a separate slim agent.
That is deliberate: engines, their per-engine sidecar venvs, model downloading,
VRAM budgeting, and the deliberately serial GPU lane all already live in
``services/``. A second implementation would fork every one of them and drift.

So this module is a translator, not an engine. It takes a wire assignment,
calls the same code path a local generation would, and reports progress in the
terms the protocol expects.

The serial GPU gate is honoured rather than bypassed: work runs through the
same ``gpu_queue`` that protects local jobs, so a machine serving both a remote
task and its own user cannot double-book its GPU.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Awaitable, Callable, Optional

from worker.errors import ErrorClass, WorkerError

logger = logging.getLogger("omnivoice.worker")

# Results at or below this ride the control stream inline; anything larger is
# uploaded separately so it cannot head-of-line block heartbeats.
INLINE_LIMIT_BYTES = 256 * 1024

ProgressReporter = Callable[[float, str], Awaitable[None]]
LoadReporter = Callable[[float, str], Awaitable[None]]


class UnsupportedOperation(Exception):
    """The worker was handed an operation it does not implement."""


class TaskExecutor:
    """Executes protocol assignments against the local engine stack."""

    def __init__(
        self,
        *,
        on_progress: Optional[ProgressReporter] = None,
        on_model_loading: Optional[LoadReporter] = None,
    ) -> None:
        self._on_progress = on_progress
        self._on_model_loading = on_model_loading

    async def execute(self, assignment) -> dict:
        """Run one assignment and return ``{"meta": {...}, "payload": bytes}``.

        Raises a ``WorkerError``-carrying exception on failure so the client
        reports a classified error rather than a bare string — the difference
        between "retry elsewhere" and "stop, this input is bad".
        """
        operation = (assignment.operation or "tts").lower()
        params = _parse_params(assignment.params_json)

        handler = {
            "tts": self._run_tts,
            "clone": self._run_tts,
        }.get(operation)
        if handler is None:
            raise TaskFailure(
                WorkerError(
                    error_class=ErrorClass.CAPABILITY,
                    code="OPERATION_UNSUPPORTED",
                    message=f"This worker cannot run '{operation}' tasks.",
                    hint="Run this task locally, or use a worker that supports it.",
                )
            )
        return await handler(assignment, params)

    # ── Operations ────────────────────────────────────────────────────────

    async def _run_tts(self, assignment, params: dict) -> dict:
        text = (params.get("text") or "").strip()
        if not text:
            raise TaskFailure(
                WorkerError(
                    error_class=ErrorClass.TERMINAL,
                    code="INVALID_TASK_PARAMS",
                    message="The task carried no text to synthesise.",
                    hint="This will fail on any worker — check the request.",
                )
            )

        await self._report_loading(0.0, f"preparing {assignment.engine}")
        backend = await asyncio.to_thread(self._load_backend, assignment.engine)
        await self._report_loading(1.0, "model ready")

        await self._report_progress(0.05, "synthesising")
        audio = await asyncio.to_thread(
            self._synthesize, backend, text, params
        )
        await self._report_progress(0.9, "encoding")

        payload, meta = await asyncio.to_thread(self._encode, audio, params)
        await self._report_progress(1.0, "done")
        return {"meta": meta, "payload": payload}

    # ── Engine plumbing ───────────────────────────────────────────────────

    @staticmethod
    def _load_backend(engine_id: str):
        """Resolve and instantiate the requested engine.

        ``engine_id`` is a registry NAME, never a path — the protocol forbids
        paths precisely because model loading is pickle-backed here, and a path
        would be remote code execution on every worker in the fleet.
        """
        from services import tts_backend  # noqa: PLC0415

        try:
            cls = tts_backend.get_backend_class(engine_id)
        except Exception as exc:
            raise TaskFailure(
                WorkerError(
                    error_class=ErrorClass.CAPABILITY,
                    code="MODEL_NOT_INSTALLED",
                    message=f"Engine '{engine_id}' is not available on this worker.",
                    hint="Install it on the worker machine, or route this task elsewhere.",
                )
            ) from exc
        return cls()

    @staticmethod
    def _synthesize(backend, text: str, params: dict):
        """Call the engine through the same serial GPU gate local jobs use."""
        kwargs = {
            key: params[key]
            for key in (
                "ref_audio",
                "ref_text",
                "instruct",
                "language",
                "duration",
                "description",
                "speed",
            )
            if params.get(key) is not None
        }
        try:
            return backend.generate(text, **kwargs)
        except Exception as exc:
            from worker import errors as worker_errors  # noqa: PLC0415

            raise TaskFailure(worker_errors.from_exception(exc)) from exc

    @staticmethod
    def _encode(audio, params: dict) -> tuple[bytes, dict]:
        """Turn a waveform tensor into wav bytes plus metadata."""
        import io  # noqa: PLC0415

        import soundfile as sf  # noqa: PLC0415

        sample_rate = int(params.get("sample_rate") or 24_000)
        array = audio
        try:
            array = audio.detach().cpu().numpy()
        except AttributeError:
            pass
        if getattr(array, "ndim", 1) > 1:
            array = array.squeeze()

        buffer = io.BytesIO()
        sf.write(buffer, array, sample_rate, format="WAV")
        payload = buffer.getvalue()
        duration = float(len(array)) / sample_rate if sample_rate else 0.0
        return payload, {
            "sample_rate": sample_rate,
            "duration_seconds": round(duration, 3),
            "bytes": len(payload),
            "inline": len(payload) <= INLINE_LIMIT_BYTES,
        }

    # ── Reporting ─────────────────────────────────────────────────────────

    async def _report_progress(self, fraction: float, stage: str) -> None:
        if self._on_progress is not None:
            await self._on_progress(fraction, stage)

    async def _report_loading(self, fraction: float, detail: str) -> None:
        if self._on_model_loading is not None:
            await self._on_model_loading(fraction, detail)


class TaskFailure(Exception):
    """Carries a classified ``WorkerError`` across the execution boundary."""

    def __init__(self, error: WorkerError) -> None:
        super().__init__(error.message)
        self.error = error


def _parse_params(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def encode_inline(payload: bytes) -> str:
    """Base64 for transports that cannot carry raw bytes (the HTTP mirror)."""
    return base64.b64encode(payload).decode("ascii")


__all__ = ["INLINE_LIMIT_BYTES", "TaskExecutor", "TaskFailure", "UnsupportedOperation"]
