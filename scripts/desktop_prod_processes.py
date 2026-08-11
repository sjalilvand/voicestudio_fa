"""Safely stop Linux AppImage processes owned by this checkout."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import signal
import time
from typing import Callable


def _appimage_from_environ(raw: bytes) -> str | None:
    for item in raw.split(b"\0"):
        if item.startswith(b"APPIMAGE="):
            return os.fsdecode(item.removeprefix(b"APPIMAGE="))
    return None


def appimage_belongs_to_build(raw: bytes, build_root: Path) -> bool:
    """Require an exact debug AppImage directory and VoiceStudio filename."""
    value = _appimage_from_environ(raw)
    if not value:
        return False
    image = Path(os.path.normpath(value))
    expected_dir = build_root / "bundle" / "appimage"
    return (
        image.parent == expected_dir
        and image.name.startswith("VoiceStudio_")
        and image.name.endswith(".AppImage")
    )


def open_owned_processes(
    build_root: Path,
    proc_root: Path = Path("/proc"),
    *,
    pidfd_open: Callable[[int, int], int] | None = None,
) -> list[tuple[int, int]]:
    """Open identity-bound handles before inspecting each candidate process."""
    if pidfd_open is None:
        pidfd_open = getattr(os, "pidfd_open", None)
        if pidfd_open is None:
            raise RuntimeError("Linux pidfd support is required")
    owned: list[tuple[int, int]] = []
    for process_dir in sorted(proc_root.iterdir(), key=lambda path: path.name):
        if not process_dir.name.isdecimal():
            continue
        pid = int(process_dir.name)
        try:
            pidfd = pidfd_open(pid, 0)
        except (OSError, ProcessLookupError):
            continue
        try:
            raw = (process_dir / "environ").read_bytes()
            if appimage_belongs_to_build(raw, build_root):
                owned.append((pid, pidfd))
                continue
        except (OSError, PermissionError):
            pass
        os.close(pidfd)
    return owned


def stop_owned_processes(build_root: Path, timeout_s: float = 5.0) -> list[int]:
    """Stop only processes held by pidfds, preventing PID-reuse termination."""
    owned = open_owned_processes(build_root)
    if not owned:
        return []

    poller = select.poll()
    for _, pidfd in owned:
        poller.register(pidfd, select.POLLIN)
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + timeout_s
    exited: set[int] = set()
    while time.monotonic() < deadline and len(exited) < len(owned):
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        exited.update(fd for fd, _ in poller.poll(min(remaining_ms, 100)))

    for _, pidfd in owned:
        if pidfd not in exited:
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            except ProcessLookupError:
                pass
        os.close(pidfd)
    return [pid for pid, _ in owned]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("build_root", type=Path)
    args = parser.parse_args()
    for pid in stop_owned_processes(args.build_root):
        print(pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
