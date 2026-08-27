"""Browser-safe media normalization for local dubbing uploads (#1643/#1644)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from services import dub_pipeline as dp


def _run_local_ingest(tmp_path, monkeypatch, *, input_type="video"):
    source_path = tmp_path / ("source.wav" if input_type == "audio" else "source.mp4")
    source_path.write_bytes(b"source")
    normalized_path = tmp_path / "source.browser.mp4"
    normalized_path.write_bytes(b"normalized")
    normalized = []
    saved = []

    def ensure(path):
        normalized.append(path)
        return str(normalized_path)

    def factory(_job_id):
        async def run_proc(cmd, **_kwargs):
            output = next((str(arg) for arg in cmd if str(arg).endswith(".wav")), None)
            if output:
                with open(output, "wb") as handle:
                    handle.write(b"RIFF")
            return SimpleNamespace(returncode=0), b"", b""

        return run_proc

    monkeypatch.setattr(dp, "_ensure_browser_playable_mp4", ensure)
    monkeypatch.setattr(dp, "run_proc_factory", factory)
    monkeypatch.setattr(dp.sf, "info", lambda _path: SimpleNamespace(frames=16000, samplerate=16000))
    monkeypatch.setattr(dp, "compute_file_hash", lambda _path: "content-hash")
    monkeypatch.setattr(
        dp,
        "find_cached_job",
        lambda *_args: {
            "job_id": "cached",
            "vocals_path": None,
            "no_vocals_path": None,
            "thumb_path": None,
            "scene_cuts": [],
        },
    )
    monkeypatch.setattr(
        dp,
        "put_and_save_job",
        lambda _job_id, job, **_kwargs: saved.append(job.copy()) or True,
    )

    async def drain():
        return [
            event
            async for event in dp.ingest_pipeline(
                "browser_media",
                str(tmp_path),
                {"kind": "file", "path": str(source_path), "input_type": input_type},
            )
        ]

    asyncio.run(drain())
    return source_path, normalized_path, normalized, saved


def test_local_video_is_normalized_before_job_is_persisted(tmp_path, monkeypatch):
    source, normalized_path, normalized, saved = _run_local_ingest(tmp_path, monkeypatch)

    assert normalized == [str(source)]
    assert saved[-1]["video_path"] == str(normalized_path)


def test_audio_only_ingest_does_not_attempt_video_transcode(tmp_path, monkeypatch):
    source, _normalized_path, normalized, saved = _run_local_ingest(
        tmp_path, monkeypatch, input_type="audio"
    )

    assert normalized == []
    assert saved[-1]["video_path"] == str(source)
