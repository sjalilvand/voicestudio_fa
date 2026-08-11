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
import hashlib
import json
import logging
import os
from typing import Any, Awaitable, Callable, Optional

from worker.errors import ErrorClass, WorkerError

logger = logging.getLogger("omnivoice.worker")

# Results at or below this ride the control stream inline; anything larger is
# uploaded separately so it cannot head-of-line block heartbeats.
INLINE_LIMIT_BYTES = 256 * 1024

# Where the control plane reports that it could not stage an input. Mirrors
# ``codec._INPUT_ERRORS_KEY``; the two are pinned together by a test rather
# than by an import, because this module must not depend on the transport.
INPUT_ERRORS_PARAM = "input_errors"

# Fetched inputs are cached by content hash, so the second clone of a voice
# transfers nothing. Bounded, because a cache with no ceiling is the same disk
# leak on the worker that unpurged artifacts were on the control plane.
INPUT_CACHE_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
_FALLBACK_INPUT_FETCH_SECONDS = 600.0

#   on_progress(fraction: float, stage: str)
#   on_model_loading(fraction: float, detail: str)
#
# Passed per call by the transport, which binds them to the assignment's ref —
# one executor serves every slot, so a reporter installed on the instance could
# not say which task a fraction belongs to. The constructor keywords remain for
# a caller that drives the executor directly.
ProgressReporter = Callable[[float, str], Awaitable[None]]
LoadReporter = Callable[[float, str], Awaitable[None]]

#   fetch_input(ref: ArtifactRef, destination: str) -> Awaitable[Any]
#
# Supplied by the transport, which owns the ``DownloadArtifact`` stream and the
# session credentials it needs. The executor decides *what* to fetch and where
# it lands; it does not know there is a network.
InputFetcher = Callable[[Any, str], Awaitable[Any]]

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
        fetch_input: Optional[InputFetcher] = None,
        input_dir: Optional[str] = None,
    ) -> None:
        self._on_progress = on_progress
        self._on_model_loading = on_model_loading
        self._fetch_input = fetch_input
        self._input_dir = input_dir

    async def execute(
        self,
        assignment,
        *,
        on_progress: Optional[ProgressReporter] = None,
        on_model_loading: Optional[LoadReporter] = None,
        fetch_input: Optional[InputFetcher] = None,
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
        params = await self._materialize_inputs(
            assignment, params, fetch_input or self._fetch_input
        )

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

    # ── Inputs ────────────────────────────────────────────────────────────

    async def _materialize_inputs(self, assignment, params: dict, fetch) -> dict:
        """Turn declared inputs into local files, then point the params at them.

        The control plane sends artifact ids, never paths — its own paths mean
        nothing here. So a clone arrives with ``ref_audio`` set to an id, and
        the audio itself only exists once this has fetched it. Getting that
        wrong does not fail loudly: the engine renders in the default voice and
        the user gets audio that is simply not their clone.
        """
        errors = params.get(INPUT_ERRORS_PARAM)
        if errors:
            detail = "; ".join(str(e) for e in errors) if isinstance(errors, list) else str(errors)
            raise TaskFailure(
                WorkerError(
                    error_class=ErrorClass.TERMINAL,
                    code="INPUT_UNAVAILABLE",
                    message=f"The task's input files could not be prepared: {detail}",
                    hint="Check that the reference audio still exists, then try again.",
                )
            )

        refs = [ref for ref in (getattr(assignment, "inputs", None) or []) if ref.artifact_id]
        if not refs:
            return params
        if fetch is None:
            raise TaskFailure(
                WorkerError(
                    error_class=ErrorClass.CAPABILITY,
                    code="INPUT_TRANSFER_UNSUPPORTED",
                    message="This worker cannot fetch task inputs.",
                    hint="Update the worker, or run this task on a worker that can.",
                )
            )

        _, run_budget = _budgets(assignment)
        local: dict[str, str] = {}
        for ref in refs:
            local[ref.artifact_id] = await self._bounded(
                self._fetch_one(ref, fetch),
                timeout=min(run_budget, _FALLBACK_INPUT_FETCH_SECONDS),
                code="INPUT_FETCH_TIMEOUT",
                what=f"Fetching '{ref.filename or ref.artifact_id}'",
            )
        return _rewrite_params(params, local)

    async def _fetch_one(self, ref, fetch) -> str:
        """The local copy of one input, downloaded only if we lack it.

        Content-addressed: the name is the hash the control plane computed, so
        a second clone of the same voice — or a retry of this very task on this
        worker — costs no transfer at all.
        """
        directory = self._input_dir or default_input_dir()
        os.makedirs(directory, exist_ok=True)
        destination = os.path.join(directory, _cache_name(ref))
        if _already_held(destination, ref):
            _touch(destination)
            return destination

        partial = f"{destination}.part"
        try:
            await fetch(ref, partial)
        except TaskFailure:
            raise
        except Exception as exc:
            _discard(partial)
            raise TaskFailure(
                WorkerError(
                    # Transient on purpose: an id we cannot resolve now is far
                    # more often a dropped stream than a permanently missing
                    # file, and one wasted retry beats failing real work.
                    error_class=ErrorClass.TRANSIENT,
                    code="INPUT_FETCH_FAILED",
                    message=f"Could not fetch '{ref.filename or ref.artifact_id}': {exc}",
                    hint="The control plane may have restarted; the task will be retried.",
                )
            ) from exc

        # Off the loop: hashing a source video on the event loop thread would
        # stall every heartbeat this worker owes the control plane.
        await asyncio.to_thread(_verify, partial, ref)
        os.replace(partial, destination)
        await asyncio.to_thread(_prune_input_cache, directory)
        return destination

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


def default_input_dir() -> str:
    """Where fetched inputs are cached on this worker.

    Under the app's own data directory when there is one — a worker is the
    ordinary backend in worker mode — and the system temp dir otherwise, so a
    stripped-down install still runs instead of failing on a missing path.
    """
    try:
        from core.config import DATA_DIR  # noqa: PLC0415

        return os.path.join(str(DATA_DIR), "workers", "inputs")
    except Exception:  # pragma: no cover — no app data dir on this host
        import tempfile  # noqa: PLC0415

        return os.path.join(tempfile.gettempdir(), "omnivoice-worker-inputs")


def _cache_name(ref) -> str:
    """A safe, content-addressed local name for one input.

    Never the wire filename: that is remote input, and joining it onto a
    directory is how a peer writes outside it. The hash the control plane sent
    is the identity; the extension is kept only when it is a plain one,
    because an engine that shells out to ffmpeg reads the suffix.
    """
    digest = "".join(c for c in (getattr(ref, "sha256", "") or "") if c in "0123456789abcdef")
    if len(digest) != 64:
        digest = hashlib.sha256((ref.artifact_id or "").encode("utf-8")).hexdigest()
    suffix = os.path.splitext(os.path.basename(str(getattr(ref, "filename", "") or "")))[1].lower()
    if not (1 < len(suffix) <= 9 and suffix[1:].isalnum()):
        suffix = ""
    return f"{digest}{suffix}"


def _already_held(path: str, ref) -> bool:
    """Do we already have this exact input?

    Size alone: the name is the content hash and the only writer is an atomic
    rename, so a file of the right size at this name cannot be different bytes.
    """
    try:
        expected = int(getattr(ref, "size_bytes", 0) or 0)
        return os.path.isfile(path) and (not expected or os.path.getsize(path) == expected)
    except OSError:  # pragma: no cover
        return False


def _touch(path: str) -> None:
    try:
        os.utime(path, None)
    except OSError:  # pragma: no cover
        pass


def _discard(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _verify(path: str, ref) -> None:
    """Refuse a transfer that does not match what was announced.

    A truncated reference clip does not fail — it clones three seconds of
    silence — so the check has to happen before the file is committed.
    """
    expected_size = int(getattr(ref, "size_bytes", 0) or 0)
    expected_hash = (getattr(ref, "sha256", "") or "").lower()
    try:
        actual_size = os.path.getsize(path)
    except OSError as exc:
        _discard(path)
        raise TaskFailure(
            WorkerError(
                error_class=ErrorClass.TRANSIENT,
                code="INPUT_FETCH_FAILED",
                message=f"The input '{ref.filename or ref.artifact_id}' did not arrive.",
                hint="The task will be retried.",
            )
        ) from exc

    actual_hash = ""
    if expected_hash:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        actual_hash = digest.hexdigest()

    if (expected_size and actual_size != expected_size) or (
        expected_hash and actual_hash != expected_hash
    ):
        _discard(path)
        raise TaskFailure(
            WorkerError(
                error_class=ErrorClass.TRANSIENT,
                code="INPUT_CORRUPT",
                message=f"The input '{ref.filename or ref.artifact_id}' arrived damaged.",
                hint="The transfer will be retried.",
            )
        )


def _prune_input_cache(directory: str, limit_bytes: int = INPUT_CACHE_LIMIT_BYTES) -> None:
    """Keep the input cache under its ceiling, oldest first."""
    try:
        entries = []
        total = 0
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            stat = os.stat(path)
            entries.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size
        for _mtime, size, path in sorted(entries):
            if total <= limit_bytes:
                break
            os.remove(path)
            total -= size
    except OSError:  # pragma: no cover — a full cache is not a failed task
        logger.debug("Could not prune the worker input cache", exc_info=True)


def _rewrite_params(params: dict, local: dict[str, str]):
    """Replace every artifact id in the params with its local path."""
    if isinstance(params, dict):
        return {key: _rewrite_params(value, local) for key, value in params.items()}
    if isinstance(params, list):
        return [_rewrite_params(item, local) for item in params]
    if isinstance(params, str):
        return local.get(params, params)
    return params


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


__all__ = [
    "INLINE_LIMIT_BYTES",
    "INPUT_CACHE_LIMIT_BYTES",
    "INPUT_ERRORS_PARAM",
    "InputFetcher",
    "TaskExecutor",
    "TaskFailure",
    "UnsupportedOperation",
    "default_input_dir",
]
