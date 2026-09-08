"""audio.cpp binary probe + model resolution.

audio.cpp (0xShug0/audio.cpp) is a pure-C++ ggml inference engine with
prebuilt release binaries — no Python venv, no ``transformers`` pin, so
none of the dependency-isolation machinery in ``engines._venv_probe`` or
``services.subprocess_backend`` applies. The parent instead:

1. locates a user-installed ``audiocpp_server`` (env var, user dir, or this
   package's ``bin/``), and
2. resolves the GGUF model file (explicit path, or a first-use download
   from ``audio-cpp/audio.cpp-gguf`` into the shared HF cache).

Probe order for the server binary (existing installs win, zero migration):

    1. ``${OMNIVOICE_AUDIOCPP_BIN}`` — absolute path to the binary itself.
    2. ``${OMNIVOICE_AUDIOCPP_DIR}/audiocpp_server[.exe]`` — a user-managed
       install dir (e.g. an extracted release zip, or a self-built tree).
    3. ``backend/engines/audiocpp/bin/audiocpp_server[.exe]`` — an explicitly
       installed local copy.

``is_installed()`` is a cheap file-existence check — no spawn, no network.
VoiceStudio never downloads executable code for this engine.
"""
from __future__ import annotations

import errno
import functools
import logging
import os
import platform
import subprocess  # nosec B404 -- fixed argv probes a user-selected executable
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("omnivoice.audiocpp.bootstrap")

#: Pinned audio.cpp release. BreezeTTS-2 support landed in 0.7.2 — older
#: binaries have no ``breeze_tts`` family, so the floor is also the pin.
VERSION = "v0.7.2"

#: GitHub repo serving the prebuilt binaries.
GH_REPO = "0xShug0/audio.cpp"

#: HuggingFace repo serving the GGUF model packages (not gated).
HF_MODEL_REPO = "audio-cpp/audio.cpp-gguf"

# Immutable repository revision used for the v0.7.2 Breeze-TTS-2 package.
# Pinning prevents a later upstream file replacement from silently changing
# the model exercised by this backend.
HF_MODEL_REVISION = "dc6fecccc2b0c6bdda0a8b2f38fa61394fee0b9c"

#: Model id used in the generated ``server.json`` and in speech requests.
MODEL_ID = "breeze-tts-2"

#: audio.cpp family name for BreezeTTS 2 (``--family`` / server ``family``).
FAMILY = "breeze_tts"

#: GGUF package directory inside :data:`HF_MODEL_REPO`.
PACKAGE_DIR = "Breeze-TTS-2-GGUF"

#: Default package (Q8_0, the upstream-recommended GGUF). ``bf16`` is
#: available via ``OMNIVOICE_AUDIOCPP_PACKAGE``.
DEFAULT_PACKAGE = "breeze-tts-2-q8_0.gguf"

#: Env var pointing directly at the ``audiocpp_server`` binary.
BIN_ENV = "OMNIVOICE_AUDIOCPP_BIN"

#: Env var pointing at a directory containing ``audiocpp_server``.
DIR_ENV = "OMNIVOICE_AUDIOCPP_DIR"

#: Env var overriding the GGUF package filename (e.g. the bf16 package).
PACKAGE_ENV = "OMNIVOICE_AUDIOCPP_PACKAGE"

#: Optional advanced overrides for a binary that exposes several runtimes or
#: devices. Device indices are local to the selected backend registry.
BACKEND_ENV = "OMNIVOICE_AUDIOCPP_BACKEND"
DEVICE_ENV = "OMNIVOICE_AUDIOCPP_DEVICE"

#: Env var overriding the loopback port the managed server binds.
PORT_ENV = "OMNIVOICE_AUDIOCPP_PORT"

#: Default loopback port. High and engine-specific to avoid clashing with
#: the app itself or a user-run ``audiocpp_server`` (default 8080).
DEFAULT_PORT = 17860

#: This package's owned binary dir (probe 3).
_PKG_BIN_DIR: Path = Path(__file__).parent / "bin"

# (asset filename, sha256) per platform slug, from the v0.7.2 release.
# VoiceStudio's first integration is CPU-only, so Windows and Linux use the
# upstream CPU archives. Upstream publishes macOS binaries under the Metal
# package name; those builds retain the CPU backend selected by VoiceStudio.
# No linux-aarch64 prebuilt exists, so that platform is unavailable in v1.
_ASSETS: dict[str, tuple[str, str]] = {
    "windows-x64": (
        "audio-v0.7.2-bin-windows-x64-cpu-portable.zip",
        "0b1f4bd78c5226ee3fa0eb24d95d603a429439cdf5dab45872d44a87412dd8c1",
    ),
    "linux-x64": (
        "audio-v0.7.2-bin-ubuntu-x64-cpu.tar.gz",
        "6f5e43dd7b80e8ddf688ef84b411fadcd1f934d2c83963178bc4e2d9c4f07736",
    ),
    "darwin-arm64": (
        "audio-v0.7.2-bin-macos-arm64-metal.tar.gz",
        "c01e4f82971bedbe341697e63a9cebd5a5d1f72d5a9bcb51a3191f95ddab7a95",
    ),
    "darwin-x64": (
        "audio-v0.7.2-bin-macos-x64-metal.tar.gz",
        "3862270f33439077225324169313f727064f727305b54d8ce920244d75ddcc24",
    ),
}

#: Binary filename per platform.
_BINARY_NAMES = {"windows-x64": "audiocpp_server.exe"}

_REGISTRY_BACKENDS = {
    "CPU": "cpu",
    "CUDA": "cuda",
    "HIP": "hip",
    "ROCm": "hip",
    "Vulkan": "vulkan",
    "Metal": "metal",
    "MTL": "metal",
}
_BACKEND_ALIASES = {
    "cpu": "cpu",
    "cuda": "cuda",
    "hip": "hip",
    "rocm": "hip",
    "vulkan": "vulkan",
    "metal": "metal",
}


@dataclass(frozen=True)
class AudioCPPDevice:
    """One immutable device from audio.cpp's backend-local registry."""

    registry: str
    backend: str
    index: int
    name: str
    kind: str
    target: str
    hardware_family: str


@dataclass(frozen=True)
class AudioCPPSelection:
    """The runtime/device chosen for the next managed server."""

    device: AudioCPPDevice
    fallback_reason: str | None = None


def _vulkan_hardware_family(name: str) -> str:
    low = name.casefold()
    if any(token in low for token in ("nvidia", "geforce", "quadro", "tesla")):
        return "cuda"
    if any(token in low for token in ("amd", "radeon")):
        return "rocm"
    if any(token in low for token in ("intel", "arc ")):
        return "xpu"
    return "vulkan"


def _device_families(registry: str, name: str) -> tuple[str, str]:
    if registry == "CUDA":
        return "cuda", "cuda"
    if registry in {"HIP", "ROCm"}:
        return "rocm", "rocm"
    if registry in {"Metal", "MTL"}:
        return "mps", "mps"
    if registry == "Vulkan":
        return "vulkan", _vulkan_hardware_family(name)
    return "cpu", "cpu"


def parse_device_list(output: str) -> tuple[AudioCPPDevice, ...]:
    """Parse the stable stdout contract of ``--list-devices``.

    Backend diagnostics are emitted on stderr and deliberately never enter
    this parser. Unknown future registries are ignored; malformed entries for
    a registry we understand fail closed instead of selecting the wrong GPU.
    """
    devices: list[AudioCPPDevice] = []
    seen: set[tuple[str, int]] = set()
    for raw in str(output or "").splitlines():
        line = raw.strip()
        registry, colon, detail = line.partition(":")
        if not colon or registry not in _REGISTRY_BACKENDS:
            continue
        index_text, space, remainder = detail.strip().partition(" ")
        if not space or not index_text.isdecimal():
            raise RuntimeError(f"malformed audio.cpp device entry: {line[:160]}")
        index = int(index_text)
        name_and_kind, marker, kind = remainder.rpartition(" [")
        if not marker or not kind.endswith("]"):
            raise RuntimeError(f"malformed audio.cpp device entry: {line[:160]}")
        name = name_and_kind.strip()
        if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
            name = name[1:-1]
        kind = kind[:-1].strip().upper()
        if kind not in {"CPU", "GPU", "IGPU", "ACCEL", "META"}:
            raise RuntimeError(f"unknown audio.cpp device kind: {kind[:40]}")
        key = (registry, index)
        if key in seen:
            raise RuntimeError(
                f"duplicate audio.cpp device entry: {registry}:{index}"
            )
        seen.add(key)
        target, hardware_family = _device_families(registry, name)
        devices.append(AudioCPPDevice(
            registry=registry,
            backend=_REGISTRY_BACKENDS[registry],
            index=index,
            name=name,
            kind=kind,
            target=target,
            hardware_family=hardware_family,
        ))
    if not devices:
        raise RuntimeError("audio.cpp reported no recognized compute devices")
    return tuple(devices)


def _platform_slug() -> str:
    system = sys.platform
    machine = platform.machine().lower()
    if system == "win32":
        return "windows-x64"
    if system == "darwin":
        return "darwin-arm64" if machine in ("arm64", "aarch64") else "darwin-x64"
    if machine in ("x86_64", "amd64"):
        return "linux-x64"
    return f"linux-{machine}"


def binary_name(slug: str | None = None) -> str:
    """``audiocpp_server`` filename for ``slug`` (``.exe`` on Windows)."""
    return _BINARY_NAMES.get(slug or _platform_slug(), "audiocpp_server")


def _probe_paths() -> list[Path]:
    out: list[Path] = []
    direct = os.environ.get(BIN_ENV, "").strip()
    if direct:
        out.append(Path(direct))
    user_dir = os.environ.get(DIR_ENV, "").strip()
    if user_dir:
        out.append(Path(user_dir) / binary_name())
    out.append(_PKG_BIN_DIR / binary_name())
    return out


def is_installed() -> bool:
    """Cheap precedence-aware check for a usable server binary."""
    try:
        resolve_server_binary()
    except RuntimeError:
        return False
    return True


def resolve_server_binary() -> Path:
    """Resolve the ``audiocpp_server`` binary. Raises ``RuntimeError`` with
    install instructions when none is found."""
    for cand in _probe_paths():
        if cand.is_file():
            if os.name == "nt" or os.access(cand, os.X_OK):
                return cand
            raise RuntimeError(
                "audiocpp_server is not executable. Run `chmod +x "
                "audiocpp_server` on the configured binary, then restart "
                "VoiceStudio. See docs/engines/audio-cpp.md."
            )
    slug = _platform_slug()
    asset = _ASSETS.get(slug)
    if asset is None:
        raise RuntimeError(
            f"audio.cpp ships no prebuilt binary for this platform ({slug}). "
            "Build from https://github.com/0xShug0/audio.cpp and set "
            f"{BIN_ENV} to your audiocpp_server binary. See "
            "docs/engines/audio-cpp.md."
        )
    raise RuntimeError(
        "audiocpp_server not found. Download "
        f"https://github.com/{GH_REPO}/releases/download/{VERSION}/{asset[0]} "
        f"(SHA-256 {asset[1]}), verify and extract it, and set {BIN_ENV} to the "
        "audiocpp_server binary (or "
        f"{DIR_ENV} to its directory). See docs/engines/audio-cpp.md."
    )


@functools.lru_cache(maxsize=4)
def _probe_devices(binary: str) -> tuple[AudioCPPDevice, ...]:
    try:
        proc = subprocess.run(  # nosec B603 -- executable is the resolved engine binary
            [binary, "--list-devices"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "audiocpp_server device discovery timed out after 10 seconds"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"audiocpp_server device discovery could not start: {type(exc).__name__}"
        ) from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown error").strip()[:300]
        raise RuntimeError(
            f"audiocpp_server device discovery failed (code {proc.returncode}): "
            f"{detail}"
        )
    return parse_device_list(proc.stdout)


def probe_devices() -> tuple[AudioCPPDevice, ...]:
    """Return the installed binary's devices without loading a model."""
    return _probe_devices(str(resolve_server_binary()))


def _priority(device: AudioCPPDevice) -> tuple[int, int]:
    if device.backend == "cuda":
        rank = 0
    elif device.backend == "hip":
        rank = 1
    elif device.backend == "metal":
        rank = 2
    elif device.backend == "vulkan" and device.kind == "GPU":
        rank = 3
    elif device.backend == "vulkan" and device.kind in {"IGPU", "ACCEL"}:
        rank = 4
    elif device.backend == "cpu":
        rank = 6
    else:
        rank = 5
    return rank, device.index


def select_device(
    devices: tuple[AudioCPPDevice, ...],
    *,
    requested_family: str = "auto",
    backend_override: str | None = None,
    device_override: int | None = None,
    preferred_name: str = "",
) -> AudioCPPSelection:
    """Resolve one device with explicit overrides and discrete-GPU priority."""
    if backend_override:
        normalized = _BACKEND_ALIASES.get(backend_override.strip().lower())
        if normalized is None:
            valid = ", ".join(_BACKEND_ALIASES)
            raise RuntimeError(
                f"unknown audio.cpp backend '{backend_override}' (valid: {valid})"
            )
        candidates = [device for device in devices if device.backend == normalized]
        if device_override is not None:
            candidates = [
                device for device in candidates if device.index == device_override
            ]
        if not candidates:
            suffix = "" if device_override is None else f" device {device_override}"
            available = ", ".join(
                f"{device.backend}:{device.index}" for device in devices
            )
            raise RuntimeError(
                f"audio.cpp backend '{backend_override}'{suffix} is unavailable "
                f"(available: {available})"
            )
        return AudioCPPSelection(min(candidates, key=_priority))

    if device_override is not None:
        raise RuntimeError(
            f"{DEVICE_ENV} requires {BACKEND_ENV} because device indices are "
            "backend-local"
        )

    family = (requested_family or "auto").strip().lower()
    if family != "auto":
        candidates = [
            device for device in devices if device.hardware_family == family
        ]
        if candidates:
            preferred = preferred_name.casefold().strip()
            if preferred:
                named = [
                    device for device in candidates
                    if preferred in device.name.casefold()
                    or device.name.casefold() in preferred
                ]
                if named:
                    candidates = named
            return AudioCPPSelection(min(candidates, key=_priority))
        cpu = [device for device in devices if device.backend == "cpu"]
        if cpu:
            return AudioCPPSelection(
                min(cpu, key=_priority),
                f"requested {family.upper()} device is not exposed by the "
                "installed audio.cpp binary; running on CPU",
            )
        raise RuntimeError(
            f"requested {family.upper()} device is not exposed by the "
            "installed audio.cpp binary"
        )

    return AudioCPPSelection(min(devices, key=_priority))


def resolve_compute_selection(caps=None) -> AudioCPPSelection:
    """Select the runtime from engine env overrides, Settings, then auto."""
    backend_override = os.environ.get(BACKEND_ENV, "").strip() or None
    raw_device = os.environ.get(DEVICE_ENV, "").strip()
    device_override: int | None = None
    if raw_device:
        try:
            device_override = int(raw_device)
        except ValueError as exc:
            raise RuntimeError(
                f"{DEVICE_ENV} must be a non-negative integer"
            ) from exc
        if device_override < 0:
            raise RuntimeError(f"{DEVICE_ENV} must be a non-negative integer")

    if caps is None:
        from core.device_caps import detect_host_caps

        caps = detect_host_caps()
    requested = getattr(caps, "requested_family", "auto") or "auto"
    return select_device(
        probe_devices(),
        requested_family=requested,
        backend_override=backend_override,
        device_override=device_override,
        preferred_name=getattr(caps, "device_name", "") or "",
    )


def runtime_targets(devices: tuple[AudioCPPDevice, ...] | None = None) -> tuple[str, ...]:
    """Actual compute backends compiled into the selected binary."""
    found = devices if devices is not None else probe_devices()
    ordered: list[str] = []
    for device in sorted(found, key=_priority):
        if device.target not in ordered:
            ordered.append(device.target)
    return tuple(ordered)


def invalidate() -> None:
    """Forget cached binary capability discovery after an install change."""
    _probe_devices.cache_clear()


def default_asset() -> tuple[str, str] | None:
    """``(filename, sha256)`` of the release asset for this host, or None
    when upstream ships no prebuilt for it."""
    return _ASSETS.get(_platform_slug())


def server_port() -> int:
    """Loopback port for the managed server (env override or default)."""
    raw = os.environ.get(PORT_ENV, "").strip()
    if raw:
        try:
            port = int(raw)
            if 1 <= port <= 65535:
                return port
            logger.warning("Ignoring %s=%r: out of range.", PORT_ENV, raw)
        except ValueError:
            logger.warning("Ignoring %s=%r: not a number.", PORT_ENV, raw)
    return DEFAULT_PORT


def package_filename() -> str:
    """GGUF package filename (env override or the Q8_0 default)."""
    return os.environ.get(PACKAGE_ENV, "").strip() or DEFAULT_PACKAGE


def _materialize_gguf_cache_path(model_file: Path) -> Path:
    """Return a real ``.gguf`` path when the HF snapshot is a symlink.

    audio.cpp canonicalizes model paths before inspecting the suffix. The
    Hugging Face cache points the friendly ``.gguf`` snapshot name at an
    extensionless content-addressed blob, so passing that symlink makes the
    server reject a valid model. A hard link beside the snapshot keeps the
    required suffix without copying a multi-gigabyte model or escaping the
    snapshot's cleanup lifecycle.
    """
    resolved = model_file.resolve()
    if resolved.suffix.lower() == ".gguf":
        return model_file
    if model_file.suffix.lower() != ".gguf":
        raise RuntimeError(f"audio.cpp model must be a .gguf file: {model_file}")

    def _link(alias: Path) -> Path:
        try:
            os.link(resolved, alias)
        except FileExistsError:
            if not os.path.samefile(resolved, alias):
                raise RuntimeError(
                    f"audio.cpp model alias points at a different file: {alias}"
                ) from None
        return alias

    alias = model_file.with_name(
        f".{model_file.stem}-{HF_MODEL_REVISION[:12]}.audiocpp.gguf"
    )
    try:
        return _link(alias)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            # An explicit symlink may live on a different filesystem from its
            # target. Put the suffix-preserving hard link beside the resolved
            # file so no multi-gigabyte copy is needed.
            target_alias = resolved.with_name(
                f".{resolved.name}-{HF_MODEL_REVISION[:12]}.audiocpp.gguf"
            )
            try:
                return _link(target_alias)
            except OSError as target_exc:
                exc = target_exc
        raise RuntimeError(
            "audio.cpp cannot materialize the Hugging Face cache symlink as "
            f"a .gguf hard link: {exc}"
        ) from exc


def _download_progress_class() -> type:
    """Return a per-download tqdm class that heartbeats the owning job."""
    from services.model_manager import report_model_load_activity
    from utils import hf_progress

    owner_ident = threading.get_ident()
    hf_progress.install()
    base = hf_progress.tracked_tqdm_class()
    if base is None:
        from huggingface_hub.utils.tqdm import tqdm as base

    class ModelDownloadProgress(base):
        def update(self, n=1):
            report_model_load_activity(owner_ident)
            return super().update(n)

        def display(self, msg=None, pos=None):
            report_model_load_activity(owner_ident)
            return super().display(msg=msg, pos=pos)

    return ModelDownloadProgress


def resolve_model_file() -> Path:
    """Resolve the Breeze-TTS-2 GGUF file, downloading it on first use.

    An explicit ``OMNIVOICE_AUDIOCPP_MODEL`` path wins (file or directory
    containing the package file). Otherwise the package file is fetched
    from :data:`HF_MODEL_REPO` into the shared HF cache — resumable and
    hash-verified by ``huggingface_hub``.
    """
    from services.tts_backend import _retry_once_with_fresh_hf_client

    override = os.environ.get("OMNIVOICE_AUDIOCPP_MODEL", "").strip()
    if override:
        cand = Path(override)
        if cand.is_file():
            return _materialize_gguf_cache_path(cand)
        if cand.is_dir():
            inner = cand / package_filename()
            if inner.is_file():
                return _materialize_gguf_cache_path(inner)
        raise RuntimeError(
            f"OMNIVOICE_AUDIOCPP_MODEL={override} is not a GGUF file or a "
            "directory containing one."
        )

    def _download() -> str:
        from huggingface_hub import snapshot_download
        from services.model_manager import report_model_load_activity

        report_model_load_activity()
        return snapshot_download(
            repo_id=HF_MODEL_REPO,
            # Full immutable commit SHA declared above; Bandit cannot follow
            # the module constant through this nested callback.
            revision=HF_MODEL_REVISION,  # nosec B615
            allow_patterns=[f"{PACKAGE_DIR}/{package_filename()}"],
            tqdm_class=_download_progress_class(),
        )

    cached = Path(
        _retry_once_with_fresh_hf_client(_download, "audio.cpp Breeze-TTS-2")
    )
    model_file = cached / PACKAGE_DIR / package_filename()
    if not model_file.is_file():
        raise RuntimeError(
            f"Breeze-TTS-2 package {package_filename()} missing after "
            f"download from {HF_MODEL_REPO} — layout changed upstream."
        )
    return _materialize_gguf_cache_path(model_file)


__all__ = [
    "AudioCPPDevice",
    "AudioCPPSelection",
    "BACKEND_ENV",
    "BIN_ENV",
    "DEFAULT_PACKAGE",
    "DEFAULT_PORT",
    "DIR_ENV",
    "DEVICE_ENV",
    "FAMILY",
    "HF_MODEL_REPO",
    "HF_MODEL_REVISION",
    "MODEL_ID",
    "PACKAGE_DIR",
    "PACKAGE_ENV",
    "PORT_ENV",
    "VERSION",
    "_download_progress_class",
    "_materialize_gguf_cache_path",
    "binary_name",
    "default_asset",
    "invalidate",
    "is_installed",
    "package_filename",
    "parse_device_list",
    "probe_devices",
    "resolve_compute_selection",
    "resolve_model_file",
    "resolve_server_binary",
    "server_port",
    "runtime_targets",
]
