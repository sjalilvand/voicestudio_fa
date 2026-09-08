"""audio.cpp TTS backend — Breeze-TTS-2 via a managed native server.

audio.cpp (0xShug0/audio.cpp) is a pure-C++ ggml runtime: prebuilt
``audiocpp_server`` binaries for Windows/macOS/Linux, no Python venv, no
``transformers`` pin — so this engine needs neither the venv-isolation
(``engines.dots_tts``) nor the per-generate CLI-spawn (``engines
.omnivoice_gguf``) patterns. The parent instead:

1. resolves the binary + GGUF model (``bootstrap.py``),
2. spawns ONE long-lived ``audiocpp_server`` on 127.0.0.1 (lazy model load,
   so VRAM is only held after the first generate), and
3. speaks its OpenAI-style ``POST /v1/audio/speech`` per generate.

v1 serves the ``breeze_tts`` family only (Breeze-TTS-2, en+zh, voice clone
+ voice design + voice direction). The server is task-agnostic on the
speech route — reference-audio presence selects clone/direction vs design —
so a single ``task: tts`` model entry covers all three modes.

License honesty: Breeze-TTS-2 weights (``BreezeBlue/Breeze-TTS-2`` and the
audio.cpp GGUF repack) are RESEARCH AND NON-COMMERCIAL ONLY
(``BreezeBlue Research and Non-Commercial License``); only the audio.cpp
code is Apache-2.0. There is no in-tree acceptance dialog for this engine
yet (settings ``/license`` allow-list), so the restriction is surfaced in
the display name, the install hint, and ``docs/engines/audio-cpp.md`` —
not silently.
"""
from __future__ import annotations

import atexit
import base64
import io
import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from services.tts_backend import TTSBackend, TTSInputError

if TYPE_CHECKING:
    import torch  # noqa: F401

logger = logging.getLogger("omnivoice.audiocpp")

#: Engine id in the TTS registry.
ENGINE_ID = "audiocpp"

#: How long to wait for ``/health`` after spawning the server (first spawn
#: extracts nothing heavy — the model loads lazily on first generate).
_HEALTH_TIMEOUT_S = 120.0

#: Per-generate HTTP timeout. Deliberately generous — the GPU-pool generate
#: budget is the real deadline; this only reaps a wedged server. The first
#: generate also cold-loads ~3 GB of GGUF.
_GENERATE_TIMEOUT_S = 900.0


# ── pure request/config builders (unit-tested, no I/O) ──────────────────────


def build_server_config(
    *, model_id: str, family: str, model_path: str, backend: str, port: int,
) -> dict:
    """``server.json`` dict for the managed ``audiocpp_server``.

    ``lazy_load`` defers the ~3 GB GGUF load to the first generate;
    ``max_loaded_models: 1`` bounds residency to the one model we serve.
    """
    return {
        "host": "127.0.0.1",
        "port": port,
        "backend": backend,
        "device": 0,
        "threads": 1,
        "lazy_load": True,
        "max_loaded_models": 1,
        "models": [
            {
                "id": model_id,
                "family": family,
                "path": model_path,
                "task": "tts",
                "mode": "offline",
            }
        ],
    }


def build_speech_payload(
    *, model_id: str, text: str, ref_audio: Optional[str] = None,
    ref_text: Optional[str] = None, instructions: Optional[str] = None,
    guidance_scale: Optional[float] = None, seed: Optional[int] = None,
) -> dict:
    """``POST /v1/audio/speech`` JSON body.

    Field spellings verified against ``app/server/runtime.cpp``
    (``build_speech_request``): ``instructions`` (plural, OpenAI spelling)
    feeds the ``instruction`` request option; ``reference_text`` and
    ``guidance_scale``/``seed`` pass through top-level; ``voice_ref`` takes
    a ``{"type": "path", ...}`` object so the reference stays on disk
    (the 5 MiB base64 cap never bites). ``response_format: json`` returns
    the WAV base64-in-JSON — one round trip, no binary framing.
    """
    payload: dict[str, Any] = {
        "model": model_id,
        "input": text,
        "response_format": "json",
    }
    if instructions:
        payload["instructions"] = instructions
    if ref_audio:
        payload["voice_ref"] = {"type": "path", "path": str(ref_audio)}
        if ref_text:
            payload["reference_text"] = ref_text
    if guidance_scale is not None:
        payload["guidance_scale"] = float(guidance_scale)
    if seed is not None:
        payload["seed"] = int(seed)
    return payload


def decode_speech_json(obj: dict) -> tuple[int, "object"]:
    """``(sample_rate, mono float32 numpy)`` from a ``response_format=json``
    speech body. Raises ``ValueError`` on a server error payload."""
    if not isinstance(obj, dict):
        raise ValueError(f"audio.cpp speech reply is not JSON: {obj!r:.120}")
    if "audio" not in obj:
        raise ValueError(f"audio.cpp speech failed: {obj.get('error', obj)!r:.300}")
    import numpy as np
    import soundfile as sf

    wav_bytes = base64.b64decode(obj["audio"])
    wav, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
    wav = np.asarray(wav, dtype=np.float32)
    if wav.ndim > 1:
        wav = wav.mean(axis=-1)
    return int(sr), wav


# ── backend ─────────────────────────────────────────────────────────────────


class AudioCPPBackend(TTSBackend):
    """Breeze-TTS-2 through a parent-managed ``audiocpp_server``."""

    id = ENGINE_ID
    display_name = (
        "audio.cpp · Breeze-TTS-2 (native GGUF, en+zh, clone+design; "
        "weights research/non-commercial)"
    )
    supports_voice_design = True
    applies_own_mastering = True  # model-decoded 24 kHz studio output
    # audio.cpp maps our accelerator families to CUDA, HIP, Metal, or Vulkan.
    # Intel GPUs use Vulkan; NPUs have no supported backend.
    gpu_compat = ("cuda", "rocm", "mps", "xpu", "cpu")
    runs_out_of_process = True
    # Same marker SubprocessBackend sets: this engine lives in another OS
    # process. Consumers only branch the matrix label and the self-test
    # route (spawn-and-ping instead of in-process synth) — both correct
    # here; nothing assumes the stdio protocol from it.
    _is_subprocess_isolated = True
    min_vram_gb = 6.0  # 4.73 GiB Q8_0 file plus graph/session workspace

    _DEFAULT_SAMPLE_RATE = 24000  # Breeze-TTS-2 native rate

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._port: Optional[int] = None
        self._sr = self._DEFAULT_SAMPLE_RATE
        self._lock = threading.RLock()
        self._server_json: Optional[Path] = None

    # ── availability ────────────────────────────────────────────────────

    @classmethod
    def is_available(cls) -> tuple[bool, str]:
        from engines.audiocpp import bootstrap

        if not bootstrap.is_installed():
            slug_asset = bootstrap.default_asset()
            if slug_asset is None:
                return False, (
                    "audio.cpp ships no prebuilt binary for this platform. "
                    "Build from https://github.com/0xShug0/audio.cpp and set "
                    f"{bootstrap.BIN_ENV}. See docs/engines/audio-cpp.md."
                )
            return False, (
                "audiocpp_server not installed. Download "
                f"https://github.com/{bootstrap.GH_REPO}/releases/download/"
                f"{bootstrap.VERSION}/{slug_asset[0]}, extract it, and set "
                f"{bootstrap.BIN_ENV} to the audiocpp_server binary "
                f"(~3 GB Breeze-TTS-2 GGUF downloads on first generate). "
                "See docs/engines/audio-cpp.md."
            )
        return True, "ready"

    # ── TTSBackend protocol ─────────────────────────────────────────────

    @property
    def sample_rate(self) -> int:
        return self._sr

    @property
    def supported_languages(self) -> list[str]:
        return ["en", "zh"]

    def model_identity(self) -> Optional[str]:
        from engines.audiocpp import bootstrap

        return f"{bootstrap.FAMILY}/{bootstrap.package_filename()}"

    # ── server lifecycle ────────────────────────────────────────────────

    def _base_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def _ensure_loaded(self) -> None:
        """Spawn the server (once) and wait for ``/health``. Idempotent."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            self._proc = None  # stale handle — respawn below
            from engines.audiocpp import bootstrap

            binary = bootstrap.resolve_server_binary()
            model_file = bootstrap.resolve_model_file()
            backend = bootstrap.default_backend()
            self._port = bootstrap.server_port()
            config = build_server_config(
                model_id=bootstrap.MODEL_ID,
                family=bootstrap.FAMILY,
                model_path=str(model_file),
                backend=backend,
                port=self._port,
            )
            from core.config import DATA_DIR

            workdir = Path(str(DATA_DIR)) / "audiocpp"
            workdir.mkdir(parents=True, exist_ok=True)
            self._server_json = workdir / "server.json"
            self._server_json.write_text(json.dumps(config, indent=2))
            log_path = workdir / "server.log"
            logger.info(
                "audio.cpp: starting %s (backend=%s, port=%d, model=%s)",
                binary, backend, self._port, model_file.name,
            )
            log_fh = open(log_path, "ab")
            try:
                self._proc = subprocess.Popen(
                    [str(binary), "--config", str(self._server_json)],
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=(os.name != "nt"),
                )
            except Exception:
                log_fh.close()
                raise
            # Popen owns the fd now; the parent handle can close.
            log_fh.close()
            atexit.register(self._terminate_server)
            self._wait_for_health()

    def _wait_for_health(self) -> None:
        assert self._proc is not None and self._port is not None
        deadline = time.monotonic() + _HEALTH_TIMEOUT_S
        last_err = "unknown"
        url = self._base_url() + "/health"
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                from engines.audiocpp.bootstrap import BACKEND_ENV

                raise RuntimeError(
                    "audiocpp_server exited during startup "
                    f"(code {self._proc.returncode}). See the server log next "
                    "to server.json under the app data audiocpp/ directory — "
                    "common cause: requested backend not in this binary, or "
                    "the port is taken. "
                    f"Set {BACKEND_ENV} to cpu as a fallback."
                )
            try:
                # ``url`` is always the hard-coded loopback host plus a
                # validated integer port; arbitrary schemes are impossible.
                with urllib.request.urlopen(url, timeout=5) as resp:  # nosec B310
                    if resp.status == 200:
                        logger.info("audio.cpp: server healthy on %s", self._base_url())
                        return
                    last_err = f"HTTP {resp.status}"
            except Exception as exc:  # noqa: BLE001 — still starting; retry
                last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0)
        self._terminate_server()
        raise RuntimeError(
            f"audiocpp_server did not become healthy within "
            f"{_HEALTH_TIMEOUT_S:.0f}s (last: {last_err})."
        )

    def _post_json(self, path: str, payload: dict, timeout: float) -> dict:
        """POST JSON to the managed server, return the decoded JSON body."""
        assert self._port is not None
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._base_url() + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            # ``req`` targets only ``_base_url()`` (127.0.0.1 + validated
            # integer port), never a caller-provided URL.
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"audio.cpp {path} failed (HTTP {exc.code}): {detail}"
            ) from exc

    def _terminate_server(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001 — kill as last resort, never raise
            try:
                proc.kill()
            except Exception as exc:  # noqa: BLE001 — process is already failing
                logger.debug("audio.cpp: final server kill failed: %s", exc)

    # ── generate ────────────────────────────────────────────────────────

    def generate(self, text: str, **kw) -> "torch.Tensor":
        import torch

        if not text or not text.strip():
            raise TTSInputError(
                "audio.cpp: the input contains no speakable text — "
                "send at least one word."
            )
        ref_audio = kw.get("ref_audio")
        ref_text = kw.get("ref_text")
        if ref_text and not ref_audio:
            logger.info(
                "audio.cpp: ref_text supplied without ref_audio; ignoring."
            )
            ref_text = None

        # Voice design: our `description=` (no ref) and voice direction
        # (`instruct=` + ref) both ride the server's `instructions` field —
        # verified spelling against app/server/runtime.cpp.
        instruct = kw.get("instruct") or kw.get("description") or None

        language = kw.get("language")
        if language and str(language).strip().lower() not in {
            "auto", "en", "english", "zh", "chinese",
        }:
            logger.info(
                "audio.cpp (Breeze-TTS-2) is en+zh only; ignoring "
                "language=%r.", language,
            )
        if kw.get("speed", 1.0) != 1.0:
            logger.info("audio.cpp: speed is not supported; ignoring.")

        from engines.audiocpp import bootstrap

        with self._lock:
            self._ensure_loaded()
            payload = build_speech_payload(
                model_id=bootstrap.MODEL_ID,
                text=text,
                ref_audio=str(ref_audio) if ref_audio else None,
                ref_text=ref_text,
                instructions=instruct,
                guidance_scale=kw.get("guidance_scale", 1.0),
                seed=kw.get("seed"),
            )
            obj = self._post_json(
                "/v1/audio/speech", payload, timeout=_GENERATE_TIMEOUT_S,
            )
        sr, wav_np = decode_speech_json(obj)
        self._sr = sr
        wav = torch.from_numpy(wav_np).float()
        if wav.ndim == 0:
            raise RuntimeError("audio.cpp produced empty audio")
        return wav.unsqueeze(0)

    # ── lifecycle ───────────────────────────────────────────────────────

    def unload(self) -> None:
        """Free the model server-side, then stop it. Idempotent."""
        with self._lock:
            if self._port is not None and self._proc is not None \
                    and self._proc.poll() is None:
                try:
                    self._post_json("/v1/tasks/unload_all_models", {}, timeout=30)
                except Exception as exc:  # noqa: BLE001 — best effort
                    logger.warning("audio.cpp: server unload failed: %s", exc)
            self._port = None
            self._terminate_server()
        super().unload()


__all__ = [
    "ENGINE_ID",
    "AudioCPPBackend",
    "build_server_config",
    "build_speech_payload",
    "decode_speech_json",
]
