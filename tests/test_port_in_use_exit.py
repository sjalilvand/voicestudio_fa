"""#1223: a port conflict must exit with a code the shell can recognise.

The reporter's backend died with `[Errno 10048] error while attempting to bind
on address ('127.0.0.1', 3900)` — port already taken, almost certainly by an
orphan from a previous session. uvicorn re-raised the bare OSError, Python
exited 1, and the desktop shell reported "Backend died (exit code 1)" with no
cause: the Windows wording is OS-translated (the report was in Russian), so no
English phrase in the log could be matched.

The fix is to make the signal locale-independent — a dedicated exit code that
`frontend/src-tauri/src/backend.rs` and `frontend/src/utils/backendCrash.ts`
both key off. This test pins the code and its cross-language agreement; the
matcher side is pinned in frontend/src/test/portInUseHint.test.js.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXPECTED_EXIT = 78  # EX_CONFIG


def _read(*parts: str) -> str:
    with open(os.path.join(_REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_backend_declares_the_exit_code():
    src = _read("backend", "main.py")
    assert f"_EXIT_PORT_IN_USE = {_EXPECTED_EXIT}" in src


def test_rust_shell_agrees_on_the_exit_code():
    """The Rust side reads this code to distinguish a conflict from a crash —
    a silent divergence would restore the unexplained "exit code 1"."""
    src = _read("frontend", "src-tauri", "src", "backend.rs")
    match = re.search(r"pub const EXIT_PORT_IN_USE: i32 = (\d+);", src)
    assert match, "EXIT_PORT_IN_USE missing from backend.rs"
    assert int(match.group(1)) == _EXPECTED_EXIT


def test_frontend_crash_hint_agrees_on_the_exit_code():
    src = _read("frontend", "src", "utils", "backendCrash.ts")
    assert f"marker.exit_code === {_EXPECTED_EXIT}" in src


@pytest.mark.parametrize("errno", [48, 98, 10048])
def test_every_platforms_eaddrinuse_is_recognised(errno):
    """EADDRINUSE is 48 on macOS/BSD, 98 on Linux, 10048 on Windows. Matching
    the errno rather than the message is the whole point — the message is
    translated by the OS."""
    src = _read("backend", "main.py")
    match = re.search(r"errno in \(([\d, ]+)\)", src)
    assert match, "errno guard missing from main.py"
    assert str(errno) in {p.strip() for p in match.group(1).split(",")}


def test_uvicorn_swallows_the_bind_error_into_systemexit(tmp_path):
    """The assumption the first version of this fix got wrong.

    `except OSError` around `uvicorn.run()` looks obviously right and is
    inert: uvicorn catches the bind failure inside its own startup, logs the
    raw errno, and raises `SystemExit(1)`. Nothing propagates. This test
    documents that behaviour against the real installed uvicorn, so a future
    refactor back to the "obvious" shape fails here instead of silently
    restoring "Backend died (exit code 1)".
    """
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        script = tmp_path / "naive.py"
        script.write_text(
            "import sys\n"
            "import uvicorn\n"
            "from fastapi import FastAPI\n"
            "try:\n"
            f"    uvicorn.run(FastAPI(), host='127.0.0.1', port={port}, "
            "log_level='critical')\n"
            "except OSError:\n"
            "    print('OSERROR', file=sys.stderr); sys.exit(78)\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True
        )
        assert "OSERROR" not in proc.stderr, (
            "uvicorn now propagates the bind OSError — the pre-probe in "
            "main.py can be simplified, but verify before doing so"
        )
        assert proc.returncode == 1
    finally:
        holder.close()


def test_real_bind_conflict_exits_with_the_dedicated_code(tmp_path):
    """End-to-end against the REAL uvicorn: hold a port, run main.py's guard
    shape against it, and confirm the process exits 78 with an actionable
    message — not uvicorn's bare exit 1.

    Reproduces the guard rather than booting the whole backend (a real boot
    downloads models), but drives genuine `uvicorn.run` so the swallowed-
    SystemExit trap above cannot silently reappear.
    """
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        guard = _read("backend", "main.py")
        start = guard.index("    def _port_taken(")
        end = guard.index("    # #1223: uvicorn does NOT")
        body = "\n".join(line[4:] for line in guard[start:end].splitlines())

        script = tmp_path / "guarded.py"
        script.write_text(
            "import socket, sys\n"
            "import uvicorn\n"
            "from fastapi import FastAPI\n"
            f"_EXIT_PORT_IN_USE = {_EXPECTED_EXIT}\n"
            f"_port = {port}\n"
            "app = FastAPI()\n"
            + body
            + "\n"
            "if (_e := _port_taken('127.0.0.1', _port)) is not None:\n"
            "    _fail_port_in_use(_e)\n"
            "try:\n"
            "    uvicorn.run(app, host='127.0.0.1', port=_port, log_level='critical')\n"
            "except SystemExit:\n"
            "    if _port_taken('127.0.0.1', _port) is not None:\n"
            "        _fail_port_in_use(None)\n"
            "    raise\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True
        )
        assert proc.returncode == _EXPECTED_EXIT, (
            f"expected exit {_EXPECTED_EXIT}, got {proc.returncode}\n{proc.stderr}"
        )
        assert "already in use" in proc.stderr
    finally:
        holder.close()


def test_the_probe_does_not_false_positive_on_a_free_port(tmp_path):
    """A free port must start normally. The probe uses uvicorn's own socket
    options (SO_REUSEADDR off Windows) precisely so a TIME_WAIT socket uvicorn
    could bind isn't reported as taken."""
    guard = _read("backend", "main.py")
    start = guard.index("    def _port_taken(")
    end = guard.index("    def _fail_port_in_use(")
    body = "\n".join(line[4:] for line in guard[start:end].splitlines())

    free = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()  # now free (possibly TIME_WAIT)

    script = tmp_path / "probe.py"
    script.write_text(
        "import socket, sys\n" + body + "\n"
        f"print('TAKEN' if _port_taken('127.0.0.1', {port}) is not None else 'FREE')\n",
        encoding="utf-8",
    )
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert proc.stdout.strip() == "FREE", proc.stderr
