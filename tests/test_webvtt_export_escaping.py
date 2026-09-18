"""Exported WebVTT escapes `&`, `<` and `>` in cue text.

In WebVTT cue text a raw `<` opens a tag, so a player drops everything after
it: Chromium renders the cue "I <3 you" as "I ". Both WebVTT writers, the dub
subtitle download and the OpenAI-compatible transcription's ``vtt`` format,
wrote segment text verbatim. The dual layout's own ``<i>`` stays markup.
"""
from __future__ import annotations

import asyncio
import io
import os
import uuid

import pytest
from fastapi import UploadFile

os.environ.setdefault("OMNIVOICE_MODEL", "test")

_TEXT = "I <3 you & a < b --> c"
_ESCAPED = "I &lt;3 you &amp; a &lt; b --&gt; c"


@pytest.fixture()
def dub_job():
    from services.dub_pipeline import _dub_jobs

    job_id = str(uuid.uuid4())[:8]
    _dub_jobs[job_id] = {
        "video_path": "/nonexistent/original.mp4",
        "duration": 10.0,
        "filename": "clip.mp4",
        "segments": [
            {"id": 0, "start": 1.0, "end": 3.0, "text": _TEXT, "text_original": "Tom & Jerry <3"},
        ],
    }
    yield job_id
    _dub_jobs.pop(job_id, None)


def _cue_text(vtt: str) -> list[str]:
    lines = vtt.splitlines()
    start = next(i for i, line in enumerate(lines) if "-->" in line and line[:2].isdigit())
    return [line for line in lines[start + 1:] if line]


def test_dub_vtt_download_escapes_cue_text(dub_job):
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app, client=("127.0.0.1", 50000))

    plain = client.get(f"/dub/vtt/{dub_job}")
    assert plain.status_code == 200
    assert _cue_text(plain.text) == [_ESCAPED]

    dual = client.get(f"/dub/vtt/{dub_job}", params={"dual": "true"})
    assert dual.status_code == 200
    assert _cue_text(dual.text) == [_ESCAPED, "<i>Tom &amp; Jerry &lt;3</i>"]


def test_imported_webvtt_round_trips_without_double_escaping():
    from fastapi.testclient import TestClient
    from main import app
    from services.dub_pipeline import _dub_jobs
    from services.srt_parser import parse_srt

    cues = ["Q&amp;A with Tom &amp; Jerry", "I &lt;3 you &gt;&gt; ok"]
    imported = "WEBVTT\n\n" + "".join(
        f"00:00:0{2 * i + 1}.000 --> 00:00:0{2 * i + 2}.000\n{cue}\n\n" for i, cue in enumerate(cues)
    )
    job_id = str(uuid.uuid4())[:8]
    _dub_jobs[job_id] = {
        "video_path": "/nonexistent/original.mp4",
        "duration": 10.0,
        "filename": "clip.mp4",
        "segments": parse_srt(imported).segments,
    }
    try:
        client = TestClient(app, client=("127.0.0.1", 50000))
        exported = client.get(f"/dub/vtt/{job_id}")
    finally:
        _dub_jobs.pop(job_id, None)

    assert exported.status_code == 200
    assert [line for line in exported.text.splitlines() if line in cues] == cues


def test_dub_srt_download_keeps_text_as_written(dub_job):
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app, client=("127.0.0.1", 50000))

    srt = client.get(f"/dub/srt/{dub_job}")
    assert srt.status_code == 200
    assert _TEXT in srt.text.splitlines()


def test_openai_compat_vtt_transcription_escapes_cue_text(monkeypatch):
    from api.routers import openai_compat
    from services import asr_backend

    async def fake_guarded(executor, fn, **kwargs):
        return {"segments": [{"start": 0.0, "end": 2.0, "text": _TEXT}], "language": "en"}

    monkeypatch.setattr(asr_backend, "asr_model_missing_error", lambda: None)
    monkeypatch.setattr(asr_backend, "run_transcribe_guarded", fake_guarded)

    upload = UploadFile(file=io.BytesIO(b"RIFF"), filename="clip.wav")
    response = asyncio.run(openai_compat.create_transcription(
        file=upload, model="whisper-1", language=None, prompt=None,
        response_format="vtt", temperature=None,
    ))

    assert _cue_text(response.body.decode("utf-8")) == [_ESCAPED]
