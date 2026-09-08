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
import logging
import os
import platform
import sys
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


def invalidate() -> None:
    """No-op cache hook — resolution is env + filesystem, nothing memoised.

    Present so tests can treat this module like the other engine
    bootstraps (``engines.dots_tts.bootstrap.invalidate``).
    """


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
        for attempt in range(2):
            try:
                os.link(resolved, alias)
            except FileExistsError:
                if (
                    not alias.is_symlink()
                    and alias.is_file()
                    and os.path.samefile(resolved, alias)
                ):
                    return alias
                if attempt == 0 and alias.is_symlink():
                    alias.unlink()
                    continue
                raise RuntimeError(
                    f"audio.cpp model alias points at a different file: {alias}"
                ) from None
            return alias
        raise RuntimeError(f"audio.cpp model alias could not be created: {alias}")

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


def resolve_model_file() -> Path:
    """Resolve an explicitly installed Breeze-TTS-2 GGUF file.

    An explicit ``OMNIVOICE_AUDIOCPP_MODEL`` path wins (file or directory
    containing the package file). Otherwise only the local Hugging Face cache
    is inspected. Downloads must be started explicitly from Model Catalogue →
    Models, so generation can never silently transfer the 4.73 GiB package.
    """
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

    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import LocalEntryNotFoundError

    try:
        cached = Path(
            snapshot_download(
                repo_id=HF_MODEL_REPO,
                # Full immutable commit SHA declared above; Bandit cannot follow
                # the module constant through this call.
                revision=HF_MODEL_REVISION,  # nosec B615
                allow_patterns=[f"{PACKAGE_DIR}/{package_filename()}"],
                local_files_only=True,
            )
        )
    except (LocalEntryNotFoundError, OSError) as exc:
        raise RuntimeError(
            "Breeze-TTS-2 is not installed. Install the audio.cpp Breeze-TTS-2 "
            "model from Model Catalogue → Models, or set "
            "OMNIVOICE_AUDIOCPP_MODEL to an existing GGUF file."
        ) from exc
    model_file = cached / PACKAGE_DIR / package_filename()
    if not model_file.is_file():
        raise RuntimeError(
            f"Breeze-TTS-2 package {package_filename()} is not completely "
            "installed. Reinstall it from Model Catalogue → Models."
        )
    return _materialize_gguf_cache_path(model_file)


__all__ = [
    "BIN_ENV",
    "DEFAULT_PACKAGE",
    "DEFAULT_PORT",
    "DIR_ENV",
    "FAMILY",
    "HF_MODEL_REPO",
    "HF_MODEL_REVISION",
    "MODEL_ID",
    "PACKAGE_DIR",
    "PACKAGE_ENV",
    "PORT_ENV",
    "VERSION",
    "_materialize_gguf_cache_path",
    "binary_name",
    "default_asset",
    "invalidate",
    "is_installed",
    "package_filename",
    "resolve_model_file",
    "resolve_server_binary",
    "server_port",
]
