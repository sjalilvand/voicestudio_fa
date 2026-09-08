"""Clearing the Tauri tab must not destroy the backend's stderr.

`/system/logs/tauri/clear` iterated every candidate in `_tauri_log_candidates()`
and truncated each one — including `backend_err.log`, the spawned backend's
stderr. Three things make that a data-loss bug rather than a tidy-up:

- The tab that owns the button does not show it. On desktop the Frontend/Tauri
  panel goes through the Rust `read_log_tail` command, whose `tauri_log_path()`
  resolves `tauri.log` and nothing else, so the user truncates a file they were
  never shown.
- `src-tauri/src/backend.rs::open_err_log_for_run()` opens it **append-only**
  so "a respawn must not destroy the previous run's evidence" (#1510) and
  rotates it to `.1` rather than truncating. It manages its own size; clearing
  it from here only undoes that.
- A native death — a Windows access violation (`0xC0000005`), a SIGSEGV — writes
  nothing to the Python log by construction, so this file is the only record
  that it happened. #1777 and #1782 are both threads where the maintainer had
  to ask a reporter for this file by hand.

Clear is therefore narrowed to the shell's own log. The READ path is unchanged,
and the last test pins that: `_tauri_log_candidates()` still lists all four
files in the same order on all three platforms, because the refactor that split
the list is where a silent regression would hide.
"""
from __future__ import annotations

import asyncio
import os

import pytest


@pytest.fixture
def system_mod():
    from api.routers import system

    return system


@pytest.fixture
def shell_logs(tmp_path, system_mod, monkeypatch):
    """A plugin log and both backend redirects, all non-empty."""
    plugin = tmp_path / "tauri.log"
    backend_out = tmp_path / "backend.log"
    backend_err = tmp_path / "backend_err.log"
    for f in (plugin, backend_out, backend_err):
        f.write_text(f"{f.name} content\n", encoding="utf-8")
    # Patch the composite as well as the two halves, and with raising=False, so
    # the behaviour assertions run identically against the pre-split code —
    # otherwise a fail-before check only proves the new helpers do not exist
    # yet, which is not the same as proving the bug.
    monkeypatch.setattr(
        system_mod,
        "_tauri_log_candidates",
        lambda: [str(plugin), str(backend_out), str(backend_err)],
    )
    monkeypatch.setattr(
        system_mod, "_tauri_plugin_log_candidates", lambda: [str(plugin)], raising=False
    )
    monkeypatch.setattr(
        system_mod,
        "_backend_redirect_log_candidates",
        lambda: [str(backend_out), str(backend_err)],
        raising=False,
    )
    return plugin, backend_out, backend_err


def test_clear_keeps_the_backend_stderr(system_mod, shell_logs):
    plugin, backend_out, backend_err = shell_logs

    res = asyncio.run(system_mod.clear_tauri_logs())

    assert res["cleared"] == [str(plugin)]
    assert plugin.stat().st_size == 0
    # The evidence a native crash leaves behind survives the button.
    assert backend_err.read_text(encoding="utf-8") == "backend_err.log content\n"
    assert backend_out.read_text(encoding="utf-8") == "backend.log content\n"


def test_clear_reports_nothing_when_there_is_no_plugin_log(system_mod, tmp_path, monkeypatch):
    absent = [str(tmp_path / "absent.log")]
    monkeypatch.setattr(system_mod, "_tauri_log_candidates", lambda: absent)
    monkeypatch.setattr(
        system_mod, "_tauri_plugin_log_candidates", lambda: absent, raising=False
    )
    monkeypatch.setattr(
        system_mod, "_backend_redirect_log_candidates", lambda: [], raising=False
    )

    assert asyncio.run(system_mod.clear_tauri_logs()) == {"cleared": [], "failed": 0}


@pytest.mark.parametrize(
    "platform,expected",
    [
        (
            "darwin",
            [
                "Library/Logs/{bid}/tauri.log",
                "Library/Logs/{bid}/VoiceStudio.log",
                "Library/Logs/OmniVoice/backend.log",
                "Library/Logs/OmniVoice/backend_err.log",
            ],
        ),
        (
            "linux",
            [
                ".local/share/{bid}/logs/tauri.log",
                ".config/{bid}/logs/tauri.log",
                ".local/state/OmniVoice/backend.log",
                ".local/state/OmniVoice/backend_err.log",
            ],
        ),
        (
            "win32",
            [
                "AppData/Local/{bid}/logs/tauri.log",
                "AppData/Roaming/{bid}/logs/tauri.log",
                "AppData/Local/OmniVoice/Logs/backend.log",
                "AppData/Local/OmniVoice/Logs/backend_err.log",
            ],
        ),
    ],
)
def test_the_read_candidate_list_is_unchanged(system_mod, monkeypatch, platform, expected):
    """Splitting the list must not change what `/system/logs/tauri` can reach.

    Same files, same order, on every platform — the composite is where a
    refactor slip would silently hide a log from the read path.
    """
    bid = "com.debpalash.omnivoice-studio"
    home = "/home/tester"
    monkeypatch.setattr(system_mod.sys, "platform", platform)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", home))
    for var in ("XDG_DATA_HOME", "XDG_STATE_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)
    if platform == "win32":
        monkeypatch.setenv("APPDATA", f"{home}/AppData/Roaming")
        monkeypatch.setenv("LOCALAPPDATA", f"{home}/AppData/Local")

    got = [p.replace("\\", "/") for p in system_mod._tauri_log_candidates()]

    assert got == [f"{home}/{suffix.format(bid=bid)}" for suffix in expected]
