"""``load_audio`` must survive torchaudio 2.9 without TorchCodec (#1931).

torchaudio >= 2.9 routes ``load()`` through TorchCodec, which needs FFmpeg
*shared libraries* on the system. Where those are absent the call raises
``ImportError`` — but ``load_audio`` caught only ``(RuntimeError, OSError)``,
so the pydub fallback written for precisely this situation never ran. Every
voice-clone reference read, watermark check and dub segment load then failed
with "TorchCodec is required for load_with_torchcodec".

This is the read-side twin of the ``_safe_torchaudio_save`` regression in
``tests/backend/services/test_audio_io.py``, and it reaches the same users:
#1931 established that RTX 50-series owners have no choice but to move off
the torch 2.8.0 pin, which has no sm_120 kernels.

Note that ``backend="soundfile"`` does not avoid this — torchaudio 2.9
accepts that argument and ignores it.
"""
from __future__ import annotations

import numpy as np
import soundfile as sf
import torch

from omnivoice.utils.audio import load_audio


def _write_sine_wav(path, *, seconds: float = 0.5, sample_rate: int = 24000):
    n = int(seconds * sample_rate)
    t = np.arange(n, dtype=np.float32) / sample_rate
    sf.write(str(path), 0.5 * np.sin(2 * np.pi * 440.0 * t), sample_rate,
             subtype="PCM_16")
    return sample_rate


def _torchcodec_missing(*_a, **_kw):
    raise ImportError(
        "TorchCodec is required for load_with_torchcodec. "
        "Please install torchcodec to use this function."
    )


def test_load_audio_falls_back_when_torchcodec_missing(tmp_path, monkeypatch):
    """Without the ImportError catch this raises instead of returning audio."""
    import torchaudio

    ref = tmp_path / "ref.wav"
    sample_rate = _write_sine_wav(ref)
    monkeypatch.setattr(torchaudio, "load", _torchcodec_missing)

    waveform = load_audio(str(ref), sample_rate)

    assert isinstance(waveform, torch.Tensor)
    assert waveform.ndim == 2, f"expected (1, T), got {tuple(waveform.shape)}"
    assert waveform.shape[0] == 1, "load_audio must return mono"
    assert waveform.shape[-1] > 0
    assert waveform.abs().max() > 0.05, "fallback produced silence"


def test_load_audio_fallback_resamples_to_target(tmp_path, monkeypatch):
    """The fallback path must still honour the requested sampling rate."""
    import torchaudio

    ref = tmp_path / "ref_16k.wav"
    _write_sine_wav(ref, seconds=0.5, sample_rate=16000)
    monkeypatch.setattr(torchaudio, "load", _torchcodec_missing)

    waveform = load_audio(str(ref), 24000)

    # 0.5 s resampled 16k -> 24k is ~12000 samples; allow resampler edge slack.
    assert abs(waveform.shape[-1] - 12000) <= 64, (
        f"expected ~12000 samples at 24 kHz, got {waveform.shape[-1]}"
    )
