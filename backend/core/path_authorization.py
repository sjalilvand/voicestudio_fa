"""Consume one-shot host paths authorized by the native Tauri process.

The web API never accepts a filesystem destination or executable path. Tauri
validates the user's native IPC request, writes a private capability file, and
only the unguessable capability token crosses loopback HTTP.
"""
from __future__ import annotations

import json
import os
import re
import stat

_TOKEN_RE = re.compile(r"[0-9a-f]{64}\Z")
_KINDS = {"models_dir", "ffmpeg", "ffprobe"}


class PathAuthorizationError(ValueError):
    pass


def consume(token: str, expected_kind: str) -> str:
    """Consume and return a single Tauri-authorized path.

    Capability files are one-shot and opened without following symlinks. The
    containing directory is supplied only to the desktop-spawned backend; a
    source/Docker backend has no path-authority channel by design.
    """
    if expected_kind not in _KINDS or not _TOKEN_RE.fullmatch(token or ""):
        raise PathAuthorizationError("Invalid or expired desktop authorization")
    root = os.environ.get("OMNIVOICE_PATH_AUTH_DIR", "")
    if not root:
        raise PathAuthorizationError("This path can only be selected in the desktop app")
    candidate = os.path.join(root, f"{token}.json")
    claimed = os.path.join(root, f".{token}.consuming")
    try:
        os.replace(candidate, claimed)
    except OSError as exc:
        raise PathAuthorizationError("Invalid or expired desktop authorization") from exc
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(claimed, flags)
    except OSError as exc:
        raise PathAuthorizationError("Invalid or expired desktop authorization") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16_384:
            raise PathAuthorizationError("Invalid desktop authorization")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise PathAuthorizationError("Invalid desktop authorization") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(claimed)
        except OSError:
            pass
    if not isinstance(payload, dict):
        raise PathAuthorizationError("Invalid desktop authorization")
    if payload.get("kind") != expected_kind or not isinstance(payload.get("path"), str):
        raise PathAuthorizationError("Desktop authorization does not match this setting")
    return payload["path"]
