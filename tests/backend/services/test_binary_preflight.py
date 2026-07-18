"""services.binary_preflight — pre-exec validation for managed executables.

The #1172 class: any file OmniVoice execs (bundled bin/ runtimes, engine
venv interpreters) must be validated first so a zero-byte placeholder /
truncated download / git-lfs pointer surfaces as a typed, actionable
InvalidBinaryError instead of an OSError errno at spawn time.
"""
from __future__ import annotations

import sys

import pytest

from services.binary_preflight import (
    InvalidBinaryError,
    looks_like_executable,
    validate_executable,
)


def test_missing_file_rejected(tmp_path):
    ok, reason = looks_like_executable(tmp_path / "nope")
    assert ok is False
    assert "missing" in reason


def test_zero_byte_placeholder_rejected(tmp_path):
    p = tmp_path / "omnivoice-tts-darwin-arm64"
    p.write_bytes(b"")
    p.chmod(0o755)
    ok, reason = looks_like_executable(p)
    assert ok is False
    assert "placeholder" in reason


def test_garbage_content_rejected(tmp_path):
    p = tmp_path / "tool"
    p.write_bytes(b"<html>error page saved as a binary</html>")
    ok, reason = looks_like_executable(p)
    assert ok is False
    assert "not a recognized executable" in reason


def test_git_lfs_pointer_rejected_with_lfs_hint(tmp_path):
    p = tmp_path / "tool"
    p.write_bytes(
        b"version https://git-lfs.github.com/spec/v1\n"
        b"oid sha256:deadbeef\nsize 12345\n"
    )
    ok, reason = looks_like_executable(p)
    assert ok is False
    assert "git lfs pull" in reason


@pytest.mark.parametrize(
    "magic",
    [
        b"\x7fELF",              # Linux
        b"MZ",                   # Windows PE
        b"\xcf\xfa\xed\xfe",     # Mach-O 64 LE (modern macOS)
        b"\xca\xfe\xba\xbe",     # Mach-O universal
        b"#!/bin/sh\n",          # shebang wrapper
    ],
)
def test_real_executable_magics_accepted(tmp_path, magic):
    p = tmp_path / "tool"
    p.write_bytes(magic + b"rest-of-binary")
    ok, reason = looks_like_executable(p)
    assert ok is True, reason


def test_current_python_interpreter_accepted():
    """The interpreter running this test is by definition a real
    executable — the validator must accept it on every platform."""
    ok, reason = looks_like_executable(sys.executable)
    assert ok is True, reason


def test_validate_executable_raises_typed_error_with_hint(tmp_path):
    p = tmp_path / "engine-python"
    p.write_bytes(b"")
    with pytest.raises(InvalidBinaryError) as exc_info:
        validate_executable(p, hint="reinstall the engine from Settings → Engines")
    err = exc_info.value
    assert isinstance(err, RuntimeError)  # select_default_engine catch contract
    assert err.path == p
    assert "reinstall the engine" in str(err)


def test_validate_executable_passes_valid_binary(tmp_path):
    p = tmp_path / "ok-bin"
    p.write_bytes(b"\x7fELFxxxx")
    validate_executable(p)  # must not raise
