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

#   on_progress(fraction: float, stage: str)
#   on_model_loading(fraction: float, detail: str)
#
# Passed per call by the transport, which binds them to the assignment's ref —
# one executor serves every slot, so a reporter installed on the instance could
# not say which task a fraction belongs to. The constructor keywords remain for
# a caller that drives the executor directly.
ProgressReporter = Callable[[float, str], Awaitable[None]]
LoadReporter = Callable[[float, str], Awaitable[None]]

# Used when an assignment carries no deadlines (the HTTP mirror, and tests).
# Generous on purpose: the server lease is the real bound, and a worker-side
# timeout that fires first turns a slow-but-healthy job into a hard failure.
_FALLBACK_MODEL_LOAD_SECONDS = 1_200.0
_FALLBACK_EXECUTION_SECONDS = 1_800.0


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

    async def execute(
        self,
        assignment,
        *,
        on_progress: Optional[ProgressReporter] = None,
        on_model_loading: Optional[LoadReporter] = None,
    ) -> dict:
        """Run one assignment and return ``{"meta": {...}, "payload": bytes}``.

        Raises a ``WorkerError``-carrying exception on failure so the client
        reports a classified error rather than a bare string — the difference
        between "retry elsewhere" and "stop, this input is bad".

        The reporters arrive per call, already bound to this assignment's ref
        by the transport; they are what renews the server's progress lease, so
        an executor that ignored them would die of apparent silence on any task
        longer than the lease — starting with the cold model load.
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
        return await handler(
            assignment,
            params,
            _Reporters(
                on_progress or self._on_progress,
                on_model_loading or self._on_model_loading,
            ),
        )

    # ── Operations ────────────────────────────────────────────────────────

    async def _run_tts(self, assignment, params: dict, report: "_Reporters") -> dict:
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

        load_budget, run_budget = _budgets(assignment)

        await report.loading(0.0, f"preparing {assignment.engine}")
        backend = await self._bounded(
            asyncio.to_thread(self._load_backend, assignment.engine),
            timeout=load_budget,
            code="MODEL_LOAD_TIMEOUT",
            what=f"Loading '{assignment.engine}'",
        )
        await report.loading(1.0, "model ready")

        await report.progress(0.05, "synthesising")
        audio = await self._bounded(
            asyncio.to_thread(self._synthesize, backend, text, params),
            timeout=run_budget,
            code="EXECUTION_TIMEOUT",
            what="Synthesis",
        )
        await report.progress(0.9, "encoding")

        payload, meta = await self._bounded(
            asyncio.to_thread(self._encode, audio, params, backend),
            timeout=run_budget,
            code="EXECUTION_TIMEOUT",
            what="Encoding",
        )
        await report.progress(1.0, "done")
        return {"meta": meta, "payload": payload}

    # ── Engine plumbing ───────────────────────────────────────────────────

    @staticmethod
    def _load_backend(engine_id: str):
        """Resolve the requested engine and make sure its weights are resident.

        ``engine_id`` is a registry NAME, never a path — the protocol forbids
        paths precisely because model loading is pickle-backed here, and a path
        would be remote code execution on every worker in the fleet.

        The instance comes from the process-wide cache, so the second task on
        an engine costs nothing: instantiating per task made every remote job
        pay a cold load, which is most of what the model-load budget and the
        progress lease were being blown on.

        ``ensure_ready()`` is what actually spends that budget. Every adapter
        loads lazily inside ``generate()``; without this the load phase is
        instantaneous, the cold load happens under the execution budget, and
        the two-phase split the protocol mirrors (#1033/#1037) is decorative.
        """
        from services import tts_backend  # noqa: PLC0415

        try:
            backend = tts_backend.get_engine_instance_for(engine_id)
        except Exception as exc:
            raise TaskFailure(
                WorkerError(
                    error_class=ErrorClass.CAPABILITY,
                    code="MODEL_NOT_INSTALLED",
                    message=f"Engine '{engine_id}' is not available on this worker.",
                    hint="Install it on the worker machine, or route this task elsewhere.",
                )
            ) from exc
        try:
            # Loading can mean a multi-GB download; the sweep must not decide
            # halfway through that nobody wants this engine.
            with tts_backend.engine_in_use(backend):
                backend.ensure_ready()
        except Exception as exc:
            from worker import errors as worker_errors  # noqa: PLC0415

            raise TaskFailure(worker_errors.from_exception(exc)) from exc
        return backend

    @staticmethod
    def _synthesize(backend, text: str, params: dict):
        """Call the engine through the same serial GPU gate local jobs use.

        Held against the idle sweep for the duration: a long generation touches
        the instance cache once, at the start, so on elapsed time alone it is
        indistinguishable from a model nobody wants any more.
        """
        from services import tts_backend  # noqa: PLC0415

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
            with tts_backend.engine_in_use(backend):
                return backend.generate(text, **kwargs)
        except Exception as exc:
            from worker import errors as worker_errors  # noqa: PLC0415

            raise TaskFailure(worker_errors.from_exception(exc)) from exc

    @staticmethod
    def _encode(audio, params: dict, backend=None) -> tuple[bytes, dict]:
        """Mark the waveform, then turn it into wav bytes plus metadata.

        The engine's own rate is the fallback, not a flat 24 kHz: VoxCPM2
        renders at 48 kHz, and encoding its output as 24 kHz plays it back at
        half speed.
        """
        import io  # noqa: PLC0415

        import soundfile as sf  # noqa: PLC0415

        sample_rate = int(
            params.get("sample_rate") or getattr(backend, "sample_rate", 0) or 24_000
        )
        audio = _mark(audio, sample_rate, params)
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

    # ── Bounding ──────────────────────────────────────────────────────────

    @staticmethod
    async def _bounded(coro, *, timeout: float, code: str, what: str):
        """Run ``coro`` under the server's budget for this phase.

        The worker's own bound, not a replacement for the server lease: the
        lease can only notice that frames stopped arriving, while this ends the
        wait on a thread that is never coming back. Both exist because either
        alone leaves a hole — a wedged GPU thread keeps the keepalive timer
        ticking, and a dead connection stops the lease from being renewed.
        """
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TaskFailure(
                WorkerError(
                    error_class=ErrorClass.TIMEOUT,
                    code=code,
                    message=f"{what} exceeded the {timeout:g}s budget for this task.",
                    hint="Try a shorter input, or a worker with more headroom.",
                )
            ) from exc


class _Reporters:
    """The two optional callbacks, so every call site can report unconditionally."""

    __slots__ = ("_progress", "_loading")

    def __init__(
        self,
        progress: Optional[ProgressReporter],
        loading: Optional[LoadReporter],
    ) -> None:
        self._progress = progress
        self._loading = loading

    async def progress(self, fraction: float, stage: str) -> None:
        if self._progress is not None:
            await self._progress(fraction, stage)

    async def loading(self, fraction: float, detail: str) -> None:
        if self._loading is not None:
            await self._loading(fraction, detail)


class TaskFailure(Exception):
    """Carries a classified ``WorkerError`` across the execution boundary."""

    def __init__(self, error: WorkerError) -> None:
        super().__init__(error.message)
        self.error = error


def _budgets(assignment) -> tuple[float, float]:
    """(model-load, execution) seconds for this assignment.

    Server-computed and relative — worker wall clocks are untrusted. A zero or
    missing field means "the server did not state one", never "no time".
    """
    deadlines = getattr(assignment, "deadlines", None)
    load = float(getattr(deadlines, "model_load_seconds", 0) or 0)
    run = float(getattr(deadlines, "execution_seconds", 0) or 0)
    return (
        load or _FALLBACK_MODEL_LOAD_SECONDS,
        run or _FALLBACK_EXECUTION_SECONDS,
    )


def _mark(audio, sample_rate: int, params: dict):
    """Provenance-mark synthetic audio before it is encoded (EU AI Act 50(2)).

    The decision is the CONTROL PLANE user's, carried on the assignment: the
    watermark pref belongs to whoever asked for the audio, not to whoever owns
    the GPU that rendered it. So ``force=True`` — a worker machine with the
    pref switched off must not strip the mark off someone else's output.

    Absent field means mark. A worker running an older control plane's
    assignment has no way to learn the user's answer, and the failure that
    matters here is shipping unmarked synthetic speech.
    """
    if params.get("watermark") is False:
        return audio
    try:
        from services.watermark import mark_synthetic  # noqa: PLC0415

        return mark_synthetic(
            audio, sample_rate, context="worker.executor.tts", force=True
        )
    except Exception:
        # mark_synthetic never raises by contract; an import failure on a
        # stripped-down worker install still must not lose the audio.
        logger.warning("Provenance marking unavailable on this worker", exc_info=True)
        return audio


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
