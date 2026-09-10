"""#2039 — PyTorch Whisper read uploads with soundfile, which cannot open
MP4/M4A (AAC). /transcribe and the MCP tool both accept .m4a, so every such
upload failed with "Format not recognised" before ASR ran."""
import numpy as np


def test_an_m4a_upload_reaches_the_pipeline_through_the_ffmpeg_fallback(tmp_path, monkeypatch):
    from services import asr_backend as ab

    clip = tmp_path / "memo.m4a"
    clip.write_bytes(b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 64)  # soundfile refuses it
    decoded = np.zeros(16000, dtype=np.float32)
    decoded_paths = []

    def fake_ffmpeg_decode(path):
        decoded_paths.append(path)
        return decoded

    monkeypatch.setattr(ab, "_decode_audio_16k_mono", fake_ffmpeg_decode)
    seen = {}

    def fake_pipe(inputs, **_kwargs):
        seen.update(inputs)
        return {"text": "hello", "chunks": []}

    result = ab.PyTorchWhisperBackend(asr_pipe=fake_pipe).transcribe(str(clip))

    assert result["text"] == "hello"
    assert decoded_paths == [str(clip)]
    assert seen["sampling_rate"] == 16000
    assert np.array_equal(seen["array"], decoded)
