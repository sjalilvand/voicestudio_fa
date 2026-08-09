"""Destructive endpoints must not report success when file cleanup fails."""
from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from api.routers import batch, gallery, system
from core.file_cleanup import FileCleanupError, unlink_if_present


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, audio_path):
        self.audio_path = audio_path
        self.deleted = False

    def execute(self, query, _params=()):
        if query.startswith("SELECT"):
            return _Result({"audio_path": self.audio_path})
        if query.startswith("DELETE"):
            self.deleted = True
        return _Result()


def test_unlink_missing_file_is_idempotent(tmp_path):
    assert unlink_if_present(tmp_path / "already-gone.wav") is False


def test_gallery_delete_keeps_record_when_audio_cannot_be_removed(monkeypatch):
    conn = _Connection("locked.wav")

    @contextmanager
    def fake_db():
        yield conn

    monkeypatch.setattr(gallery, "db_conn", fake_db)
    monkeypatch.setattr(
        gallery,
        "unlink_if_present",
        lambda _path: (_ for _ in ()).throw(FileCleanupError("locked")),
    )

    with pytest.raises(HTTPException) as caught:
        gallery.delete_voice("voice-1")

    assert caught.value.status_code == 500
    assert conn.deleted is False
    assert "locked.wav" not in caught.value.detail


def test_batch_delete_keeps_job_when_video_cannot_be_removed(monkeypatch):
    job = {"video_path": "locked.mp4"}
    monkeypatch.setitem(batch._jobs, "job-1", job)
    monkeypatch.setattr(
        batch,
        "unlink_if_present",
        lambda _path: (_ for _ in ()).throw(FileCleanupError("locked")),
    )

    with pytest.raises(HTTPException) as caught:
        batch.delete_batch_job("job-1")

    assert caught.value.status_code == 500
    assert batch._jobs["job-1"] is job
    assert "locked.mp4" not in caught.value.detail


def test_gallery_batch_delete_reports_failure_and_keeps_failed_record(monkeypatch):
    conn = _Connection("locked.wav")

    @contextmanager
    def fake_db():
        yield conn

    monkeypatch.setattr(gallery, "db_conn", fake_db)
    monkeypatch.setattr(
        gallery,
        "unlink_if_present",
        lambda _path: (_ for _ in ()).throw(FileCleanupError("locked")),
    )

    assert gallery.batch_delete_voices({"ids": ["voice-1"]}) == {
        "deleted": 0,
        "failed": 1,
    }
    assert conn.deleted is False


@pytest.mark.asyncio
async def test_tauri_log_clear_reports_truncate_failure(monkeypatch, tmp_path):
    log = tmp_path / "webview.log"
    log.write_text("data", encoding="utf-8")
    monkeypatch.setattr(system, "_tauri_log_candidates", lambda: [str(log)])
    monkeypatch.setattr(
        system,
        "_truncate_file",
        lambda _path: (_ for _ in ()).throw(PermissionError("locked")),
    )

    result = await system.clear_tauri_logs()

    assert result == {"cleared": [], "failed": 1}
    assert str(log) not in str(result)
