"""audio.cpp binary probe + model resolution.

audio.cpp (0xShug0/audio.cpp) is a pure-C++ ggml inference engine with
prebuilt release binaries — no Python venv, no ``transformers`` pin, so
none of the dependency-isolation machinery in ``engines._venv_probe`` or
``services.subprocess_backend`` applies. The parent instead:

1. locates ``audiocpp_server`` (env var, user dir, or this package's
   ``bin/`` populated by :func:`install_default_asset`), and
2. resolves the GGUF model file (explicit path, or a first-use download
   from ``audio-cpp/audio.cpp-gguf`` into the shared HF cache).

Probe order for the server binary (existing installs win, zero migration):

    1. ``${OMNIVOICE_AUDIOCPP_BIN}`` — absolute path to the binary itself.
    2. ``${OMNIVOICE_AUDIOCPP_DIR}/audiocpp_server[.exe]`` — a user-managed
       install dir (e.g. an extracted release zip, or a self-built tree).
    3. ``backend/engines/audiocpp/bin/audiocpp_server[.exe]`` — VoiceStudio's
       own copy, populated by :func:`install_default_asset`.

Security: release-asset SHA-256 pins are verified on every install
(download → hash → compare → extract). ``is_installed()`` is a cheap
file-existence check — no spawn, no network.
"""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("omnivoice.audiocpp.bootstrap")

#: Pinned audio.cpp release. BreezeTTS-2 support landed in 0.7.2 — older
#: binaries have no ``breeze_tts`` family, so the floor is also the pin.
VERSION = "v0.7.2"

#: GitHub repo serving the prebuilt binaries.
GH_REPO = "0xShug0/audio.cpp"

#: HuggingFace repo serving the GGUF model packages (not gated).
HF_MODEL_REPO = "audio-cpp/audio.cpp-gguf"

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

#: Env var overriding the server compute backend
#: (``cuda`` | ``vulkan`` | ``metal`` | ``cpu``).
BACKEND_ENV = "OMNIVOICE_AUDIOCPP_BACKEND"

#: Env var overriding the release asset filename (power users, e.g. the
#: Windows CUDA build — which additionally needs the matching cudart
#: archive extracted next to the binary).
ASSET_ENV = "OMNIVOICE_AUDIOCPP_ASSET"

#: Env var overriding the loopback port the managed server binds.
PORT_ENV = "OMNIVOICE_AUDIOCPP_PORT"

#: Default loopback port. High and engine-specific to avoid clashing with
#: the app itself or a user-run ``audiocpp_server`` (default 8080).
DEFAULT_PORT = 17860

#: This package's owned binary dir (probe 3).
_PKG_BIN_DIR: Path = Path(__file__).parent / "bin"

# (asset filename, sha256) per platform slug, from the v0.7.2 release.
# No Linux-CUDA prebuilt exists upstream — Linux CUDA users self-build and
# point OMNIVOICE_AUDIOCPP_BIN at their binary; the Vulkan prebuilt is the
# default because it runs on NVIDIA/AMD/Intel GPUs with no cudart sidecar.
# No linux-aarch64 prebuilt either — that platform is unavailable in v1.
_ASSETS: dict[str, tuple[str, str]] = {
    "windows-x64": (
        "audio-v0.7.2-bin-windows-x64-vulkan.zip",
        "15b8232eae740e21e507d87f827a89966de9451b085a45932d9e214e032962c1",
    ),
    "linux-x64": (
        "audio-v0.7.2-bin-ubuntu-x64-vulkan.tar.gz",
        "fee1f978cee76453cf17f00196554bc2ee294645739538af0726a143b6c20de9451b085a45932d9e214e032962c1",
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


def binary_name(slug: Optional[str] = None) -> str:
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
    """Cheap file-existence check for a usable server binary."""
    return any(p.is_file() for p in _probe_paths())


def resolve_server_binary() -> Path:
    """Resolve the ``audiocpp_server`` binary. Raises ``RuntimeError`` with
    install instructions when none is found."""
    for cand in _probe_paths():
        if cand.is_file():
            return cand
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
        f"({asset[1][:12]}…), extract it, and set {BIN_ENV} to the "
        "audiocpp_server binary (or "
        f"{DIR_ENV} to its directory). See docs/engines/audio-cpp.md."
    )


def invalidate() -> None:
    """No-op cache hook — resolution is env + filesystem, nothing memoised.

    Present so tests can treat this module like the other engine
    bootstraps (``engines.dots_tts.bootstrap.invalidate``).
    """


def default_asset() -> Optional[tuple[str, str]]:
    """``(filename, sha256)`` of the release asset for this host, or None
    when upstream ships no prebuilt for it."""
    return _ASSETS.get(_platform_slug())


def default_backend() -> str:
    """Compute backend for the managed server.

    Env override wins; otherwise Metal on macOS, Vulkan on Windows/Linux
    (matching the default prebuilt asset — the release matrix has no Linux
    CUDA binary), CPU when nothing else applies.
    """
    override = os.environ.get(BACKEND_ENV, "").strip().lower()
    if override:
        return override
    if sys.platform == "darwin":
        return "metal"
    if sys.platform == "win32" or sys.platform.startswith("linux"):
        return "vulkan"
    return "cpu"


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


def _download_url(asset: str) -> str:
    return f"https://github.com/{GH_REPO}/releases/download/{VERSION}/{asset}"


def install_default_asset(dest_dir: Optional[Path] = None) -> Path:
    """Download + SHA-verify + extract the platform release asset into
    ``dest_dir`` (default: this package's ``bin/``) and return the server
    binary path. Explicit user action only — never called implicitly."""
    slug = _platform_slug()
    asset = _ASSETS.get(slug)
    if asset is None:
        raise RuntimeError(
            f"audio.cpp ships no prebuilt binary for {slug}; build from "
            f"https://github.com/{GH_REPO} and set {BIN_ENV} instead."
        )
    filename, want_sha = asset
    target = Path(dest_dir) if dest_dir else _PKG_BIN_DIR
    target.mkdir(parents=True, exist_ok=True)
    logger.info("audio.cpp: downloading %s (%s)", _download_url(filename), slug)
    with tempfile.NamedTemporaryFile(
        prefix="audiocpp_", suffix=Path(filename).suffix, delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        urllib.request.urlretrieve(_download_url(filename), tmp_path)
        digest = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
        if digest != want_sha:
            raise RuntimeError(
                f"audio.cpp asset SHA-256 mismatch for {filename}: "
                f"got {digest}, want {want_sha}. Refusing to extract."
            )
        if filename.endswith(".zip"):
            with zipfile.ZipFile(tmp_path) as zf:
                zf.extractall(target)
        else:
            with tarfile.open(tmp_path, "r:gz") as tf:
                tf.extractall(target, filter="data")
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass
    found = _locate_binary(target)
    if found is None:
        raise RuntimeError(
            f"extracted {filename} but found no {binary_name()} under "
            f"{target} — layout changed upstream; set {BIN_ENV} manually."
        )
    if os.name != "nt":
        found.chmod(found.stat().st_mode | 0o111)
    logger.info("audio.cpp: installed %s", found)
    return found


def _locate_binary(root: Path) -> Optional[Path]:
    """Find the server binary under ``root`` (release zips nest it)."""
    want = binary_name()
    direct = root / want
    if direct.is_file():
        return direct
    for cand in sorted(root.rglob(want)):
        if cand.is_file():
            return cand
    return None


def package_filename() -> str:
    """GGUF package filename (env override or the Q8_0 default)."""
    return os.environ.get(PACKAGE_ENV, "").strip() or DEFAULT_PACKAGE


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
            return cand
        if cand.is_dir():
            inner = cand / package_filename()
            if inner.is_file():
                return inner
        raise RuntimeError(
            f"OMNIVOICE_AUDIOCPP_MODEL={override} is not a GGUF file or a "
            "directory containing one."
        )

    def _download() -> str:
        from huggingface_hub import snapshot_download

        return snapshot_download(
            repo_id=HF_MODEL_REPO,
            allow_patterns=[f"{PACKAGE_DIR}/{package_filename()}"],
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
    return model_file


__all__ = [
    "BACKEND_ENV",
    "BIN_ENV",
    "DEFAULT_PACKAGE",
    "DEFAULT_PORT",
    "DIR_ENV",
    "FAMILY",
    "HF_MODEL_REPO",
    "MODEL_ID",
    "PACKAGE_DIR",
    "PACKAGE_ENV",
    "PORT_ENV",
    "VERSION",
    "binary_name",
    "default_asset",
    "default_backend",
    "install_default_asset",
    "invalidate",
    "is_installed",
    "package_filename",
    "resolve_model_file",
    "resolve_server_binary",
    "server_port",
]
