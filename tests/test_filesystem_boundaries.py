"""Regression tests for host-filesystem and persisted-path trust boundaries."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.dependencies import require_native_access
from core.path_security import UnsafePath, resolve_within, safe_filename


def _request(host: str | None):
    return SimpleNamespace(client=SimpleNamespace(host=host) if host else None)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_native_filesystem_capabilities_allow_true_loopback(host):
    require_native_access(_request(host))


@pytest.mark.parametrize("host", ["172.17.0.1", "192.168.1.4", None])
def test_native_filesystem_capabilities_reject_remote_even_in_server_mode(monkeypatch, host):
    monkeypatch.setenv("OMNIVOICE_SERVER_MODE", "1")
    monkeypatch.setenv("OMNIVOICE_API_KEY", "operator-secret")
    with pytest.raises(HTTPException) as exc:
        require_native_access(_request(host))
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "name",
    ["../secret.wav", "folder/voice.wav", r"folder\voice.wav", r"C:\secret.wav", ".", "..", ""],
)
def test_safe_filename_rejects_posix_and_windows_escapes(name):
    with pytest.raises(UnsafePath):
        safe_filename(name)


def test_resolve_within_accepts_relative_and_existing_absolute_paths(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    item = root / "voice.wav"
    assert resolve_within(root, "voice.wav") == item
    assert resolve_within(root, item) == item


def test_resolve_within_rejects_parent_and_absolute_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(UnsafePath):
        resolve_within(root, "../secret.wav")
    with pytest.raises(UnsafePath):
        resolve_within(root, tmp_path / "secret.wav")
    with pytest.raises(UnsafePath):
        resolve_within(root, r"..\secret.wav")
    with pytest.raises(UnsafePath):
        resolve_within(root, r"C:\secret.wav")


def test_resolve_within_rejects_symlink_escape(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafePath):
        resolve_within(root, "link/secret.wav")


def test_marketplace_filename_cannot_escape_store(tmp_path, monkeypatch):
    from api.routers import marketplace

    monkeypatch.setattr(marketplace, "MARKETPLACE_DIR", tmp_path / "store")
    (tmp_path / "store").mkdir()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(marketplace.install_from_marketplace("../secret.omnivoice"))
    assert exc.value.status_code == 400


def test_marketplace_db_asset_cannot_escape_voices(tmp_path, monkeypatch):
    from api.routers import marketplace

    voices = tmp_path / "voices"
    voices.mkdir()
    secret = tmp_path / "secret.wav"
    secret.write_bytes(b"secret")
    monkeypatch.setattr(marketplace, "VOICES_DIR", str(voices))
    assert marketplace._voice_asset(secret) is None


def test_profile_lock_rejects_history_path_outside_outputs(tmp_path, monkeypatch):
    from api.routers import profiles

    outputs = tmp_path / "outputs"
    voices = tmp_path / "voices"
    outputs.mkdir()
    voices.mkdir()
    secret = tmp_path / "secret.wav"
    secret.write_bytes(b"secret")

    class FakeConnection:
        def execute(self, query, _params):
            if "voice_profiles" in query:
                return SimpleNamespace(fetchone=lambda: {"id": "profile"})
            return SimpleNamespace(
                fetchone=lambda: {"audio_path": str(secret), "text": "private"}
            )

    @contextmanager
    def fake_db_conn():
        yield FakeConnection()

    monkeypatch.setattr(profiles, "OUTPUTS_DIR", str(outputs))
    monkeypatch.setattr(profiles, "VOICES_DIR", str(voices))
    monkeypatch.setattr(profiles, "db_conn", fake_db_conn)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles.lock_profile("profile", history_id="history"))
    assert exc.value.status_code == 400
    assert not any(voices.iterdir())


def test_dub_artifact_rejects_db_path_and_symlink_escapes(tmp_path, monkeypatch):
    from api.routers import dub_export

    root = tmp_path / "dub"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.wav").write_bytes(b"secret")
    (root / "link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(dub_export, "DUB_DIR", str(root))

    for value in (outside / "secret.wav", root / "link" / "secret.wav"):
        with pytest.raises(HTTPException) as exc:
            dub_export._dub_artifact(value)
        assert exc.value.status_code == 400


def test_native_save_guard_runs_only_for_host_path_mode(monkeypatch):
    from api.routers import dub_export

    remote = _request("10.0.0.8")
    dub_export._guard_native_save(remote, "")
    with pytest.raises(HTTPException) as exc:
        dub_export._guard_native_save(remote, "/tmp/export.wav")
    assert exc.value.status_code == 403
