"""Regression tests for host-filesystem and persisted-path trust boundaries."""

from __future__ import annotations

import asyncio
import inspect
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from api.dependencies import require_native_access
from core.path_security import UnsafePath, resolve_within, safe_filename
from fastapi import HTTPException


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


def test_dub_artifact_rebases_trusted_path_after_data_relocation(tmp_path, monkeypatch):
    from api.routers import dub_export

    current = tmp_path / "new-data" / "dub_jobs"
    artifact = current / "job_123" / "tracks" / "voice.wav"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"voice")
    monkeypatch.setattr(dub_export, "DUB_DIR", str(current))

    old_posix = tmp_path / "old-data" / "dub_jobs" / "job_123" / "tracks" / "voice.wav"
    old_windows = r"D:\Old VoiceStudio\dub_jobs\job_123\tracks\voice.wav"
    assert dub_export._dub_artifact(old_posix) == str(artifact.resolve())
    assert dub_export._dub_artifact(old_windows) == str(artifact.resolve())


def test_dub_artifact_rebase_rejects_unanchored_traversal_and_symlink(tmp_path, monkeypatch):
    from api.routers import dub_export

    current = tmp_path / "new-data" / "dub_jobs"
    outside = tmp_path / "outside"
    current.mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.wav").write_bytes(b"secret")
    (current / "job_123").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(dub_export, "DUB_DIR", str(current))

    rejected = [
        tmp_path / "old-data" / "other" / "job_123" / "secret.wav",
        str(tmp_path / "old-data" / "dub_jobs" / ".." / "secret.wav"),
        tmp_path / "old-data" / "dub_jobs" / "job_123" / "secret.wav",
        r"D:\old\dub_jobs\..\secret.wav",
    ]
    for value in rejected:
        with pytest.raises(HTTPException) as exc:
            dub_export._dub_artifact(value)
        assert exc.value.status_code == 400


def test_dub_native_save_requires_one_shot_tauri_authorization(tmp_path, monkeypatch):
    from api.routers import dub_export
    from core import path_authorization

    auth_dir = tmp_path / "authorizations"
    auth_dir.mkdir()
    monkeypatch.setattr(path_authorization, "_AUTH_DIR", str(auth_dir))
    token = "a" * 64
    destination = str(tmp_path / "export.wav")
    (auth_dir / f"{token}.json").write_text(
        json.dumps({"token": token, "kind": "dub_export", "path": destination}),
        encoding="utf-8",
    )

    assert dub_export._consume_native_save("") is None
    assert dub_export._consume_native_save(token) == destination
    with pytest.raises(HTTPException) as exc:
        dub_export._consume_native_save(token)
    assert exc.value.status_code == 403


def test_dub_routes_never_accept_an_http_destination_path():
    from api.routers import dub_export

    for route in (
        dub_export.dub_download,
        dub_export.dub_download_audio,
        dub_export.dub_download_mp3,
    ):
        parameters = inspect.signature(route).parameters
        assert "save_path" not in parameters
        assert "save_authorization" in parameters
