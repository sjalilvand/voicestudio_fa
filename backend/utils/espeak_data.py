"""Point the bundled espeak-ng at a data directory it can actually open.

#3367: KittenTTS (and misaki's English fallback) phonemize through
``phonemizer`` + the ``espeakng_loader`` wheel. misaki hands espeak the
wheel's own ``espeak-ng-data`` path, but espeak-ng copies that path into a
fixed-size buffer (``N_PATH_HOME``: 230 bytes on Windows, 160 elsewhere) and
opens it with the narrow C runtime. A path that is too long, or that the
Windows ANSI code page cannot represent (a non-ASCII user name), is not seen
as a directory, so espeak silently falls back to the path baked in when the
wheel was built (``D:/a/espeakng-loader/...``). It then cannot read
``phontab`` and ``espeak_Initialize`` calls ``exit(1)``: no Python exception,
the whole backend dies mid-request.

``ensure_espeak_data_path()`` asks the library itself how it resolves each
candidate path (``espeak_ng_InitializePath`` + ``espeak_Info`` only resolve
the path; neither loads data or can exit). It uses the first candidate espeak
accepts: the wheel's own directory, its Windows 8.3 short form, then a copy
in a short cache directory. When none works it raises ``EspeakDataError``, an
ordinary engine-load failure, before phonemizer can initialize espeak and
take the process down.

Leaf module: stdlib only at import time.
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger("omnivoice.espeak")

_LOCK = threading.Lock()
_RESOLVED: str | None = None


class EspeakDataError(RuntimeError):
    """espeak-ng cannot open any copy of its data directory."""


def _same_path(a: str, b: str) -> bool:
    def norm(p: str) -> str:
        return os.path.normcase(os.path.normpath(p.rstrip("/\\")))

    return norm(a) == norm(b)


def espeak_resolves(library: str, candidate: str) -> bool | None:
    """Whether espeak-ng would use ``candidate`` as its data directory.

    ``None`` means the library could not be asked (missing symbol, load
    failure); callers treat that as "unknown" and let phonemizer report
    its own, catchable, load error.
    """
    try:
        lib = ctypes.CDLL(library)
        init_path = lib.espeak_ng_InitializePath
        info = lib.espeak_Info
    except (OSError, AttributeError):
        return None
    init_path.argtypes = [ctypes.c_char_p]
    init_path.restype = None
    info.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
    info.restype = ctypes.c_char_p
    init_path(str(candidate).encode("utf-8"))
    resolved = ctypes.c_char_p()
    info(ctypes.byref(resolved))
    if not resolved.value:
        return False
    return _same_path(resolved.value.decode("utf-8", "replace"), str(candidate))


def _windows_short_path(path: Path) -> Path | None:
    if sys.platform != "win32":
        return None
    try:
        get_short = ctypes.windll.kernel32.GetShortPathNameW  # type: ignore[attr-defined]
        size = get_short(str(path), None, 0)
        if not size:
            return None
        buf = ctypes.create_unicode_buffer(size)
        if not get_short(str(path), buf, size):
            return None
        return Path(buf.value)
    except Exception:  # pragma: no cover - best effort
        return None


def _cache_roots() -> list[Path]:
    roots: list[str | None] = [os.environ.get("OMNIVOICE_ESPEAK_DATA_CACHE")]
    if sys.platform == "win32":
        roots.append(os.environ.get("PROGRAMDATA"))
        roots.append(os.environ.get("PUBLIC"))
    else:
        roots.append(os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache"))
    roots.append(tempfile.gettempdir())
    if sys.platform != "win32":
        roots.append("/tmp")
    out: list[Path] = []
    for root in roots:
        if root and Path(root) not in out:
            out.append(Path(root))
    return out


def _cached_copy(source: Path, root: Path) -> Path | None:
    """A copy of ``source`` under ``root``; reused while the source is unchanged."""
    phontab = source / "phontab"
    try:
        stamp = f"{source}|{phontab.stat().st_size}|{phontab.stat().st_mtime_ns}"
    except OSError:
        return None
    digest = hashlib.sha256(stamp.encode("utf-8", "replace")).hexdigest()[:10]
    target = root / "voicestudio-espeak" / digest
    if (target / "phontab").is_file():
        return target
    staging = target.with_name(f"{digest}.tmp-{os.getpid()}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(source, staging)
        try:
            os.replace(staging, target)
        except OSError:
            # Another process won the race; its copy is equivalent.
            shutil.rmtree(staging, ignore_errors=True)
    except OSError as exc:
        logger.debug("espeak data copy into %s failed: %s", root, exc)
        shutil.rmtree(staging, ignore_errors=True)
        return None
    return target if (target / "phontab").is_file() else None


def _candidates(source: Path):
    yield source
    short = _windows_short_path(source)
    if short is not None:
        yield short
    for root in _cache_roots():
        copy = _cached_copy(source, root)
        if copy is not None:
            yield copy


def _apply(library: str, data_path: str) -> None:
    # misaki sets the wheel path at import time; import it first so it cannot
    # overwrite the path chosen here afterwards.
    try:
        import misaki.espeak  # noqa: F401
    except Exception:
        pass
    try:
        from phonemizer.backend.espeak.wrapper import EspeakWrapper

        EspeakWrapper.set_library(library)
        EspeakWrapper.set_data_path(data_path)
    except ImportError:
        pass
    os.environ["PHONEMIZER_ESPEAK_DATA_PATH"] = data_path
    os.environ["ESPEAK_DATA_PATH"] = data_path


def ensure_espeak_data_path(*, _loader=None) -> str | None:
    """Make phonemizer use an espeak-ng data directory espeak can open.

    Returns the chosen directory, or ``None`` when ``espeakng_loader`` is not
    installed (the engine then uses whatever espeak the system provides).
    Raises ``EspeakDataError`` instead of letting espeak ``exit(1)``.
    """
    global _RESOLVED
    if _loader is None:
        try:
            import espeakng_loader as _loader
        except ImportError:
            return None
    with _LOCK:
        if _RESOLVED is not None and (Path(_RESOLVED) / "phontab").is_file():
            _apply(_loader.get_library_path(), _RESOLVED)
            return _RESOLVED
        library = _loader.get_library_path()
        try:
            source = Path(_loader.get_data_path())
        except RuntimeError as exc:
            raise EspeakDataError(
                "The espeak-ng data bundled with this engine is missing. "
                "Reinstall the engine from Model Catalogue."
            ) from exc
        if not (source / "phontab").is_file():
            raise EspeakDataError(
                f"The espeak-ng data bundled with this engine is incomplete "
                f"(no phontab in {source}). Reinstall the engine from Model "
                f"Catalogue."
            )
        for candidate in _candidates(source):
            verdict = espeak_resolves(library, str(candidate))
            if verdict is None:
                # Cannot ask the library; keep the wheel path and let
                # phonemizer raise its own catchable load error.
                _apply(library, str(source))
                return str(source)
            if verdict:
                if candidate != source:
                    logger.info(
                        "espeak-ng cannot open %s (path too long or not "
                        "representable); using %s",
                        source, candidate,
                    )
                _apply(library, str(candidate))
                _RESOLVED = str(candidate)
                return _RESOLVED
        raise EspeakDataError(
            f"espeak-ng cannot open its data directory {source} (the path is "
            f"too long or contains characters it cannot read) and no shorter "
            f"copy could be made. Set OMNIVOICE_ESPEAK_DATA_CACHE to a short, "
            f"writable ASCII folder (for example C:\\espeak) and retry."
        )
