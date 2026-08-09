"""Explicit, ephemeral YouTube authentication for URL ingest (#1429/#1432)."""
import asyncio
import os
import stat
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend"))

from api.routers import dub_core  # noqa: E402
from services import dub_pipeline  # noqa: E402


COOKIE_TEXT = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsecret\n"


def test_cookie_export_requires_deliberate_netscape_file_and_is_private():
    with pytest.raises(HTTPException) as exc:
        dub_core._stage_cookie_export('{"cookies": []}')
    assert exc.value.status_code == 400

    path = dub_core._stage_cookie_export(COOKIE_TEXT)
    try:
        with open(path, encoding="utf-8") as cookie_file:
            assert cookie_file.read() == COOKIE_TEXT
        if os.name != "nt":
            assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    finally:
        os.unlink(path)


def test_cookie_export_is_forwarded_to_ytdlp(tmp_path, monkeypatch):
    import yt_dlp

    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download=True):
            raise RuntimeError("stop after capturing options")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    cookie_path = str(tmp_path / "cookies.txt")
    with pytest.raises(RuntimeError):
        dub_pipeline.yt_download_sync(
            "https://youtube.com/watch?v=abc",
            str(tmp_path),
            cookie_file=cookie_path,
        )

    assert captured["cookiefile"] == cookie_path


def test_pipeline_deletes_cookie_export_after_download_failure(tmp_path, monkeypatch):
    cookie_path = tmp_path / "session.cookies.txt"
    cookie_path.write_text(COOKIE_TEXT, encoding="utf-8")

    def fail_download(*_args, **_kwargs):
        raise RuntimeError("download failed")

    monkeypatch.setattr(dub_pipeline, "yt_download_sync", fail_download)
    async def collect_events():
        events = []
        async for event in dub_pipeline.ingest_pipeline(
            "cookie-cleanup",
            str(tmp_path / "job"),
            {
                "kind": "url",
                "url": "https://youtube.com/watch?v=abc",
                "cookie_file": str(cookie_path),
            },
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert any('"type": "error"' in event for event in events)
    assert not cookie_path.exists()
