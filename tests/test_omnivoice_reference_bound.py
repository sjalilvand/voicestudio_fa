"""Long cloning references must fail before unbounded tokenizer allocation (#1578)."""

from types import SimpleNamespace

import pytest
import soundfile as sf
import torch

class _Tokenizer:
    config = SimpleNamespace(hop_length=320)
    device = "cpu"

    def __init__(self, reject=True):
        self.reject = reject
        self.seen_samples = None

    def encode(self, audio):
        self.seen_samples = audio.shape[-1]
        self.seen_peak = float(audio.abs().max())
        if self.reject:
            raise AssertionError("an unsafe reference reached the audio tokenizer")
        return SimpleNamespace(audio_codes=torch.zeros((1, 1, 1), dtype=torch.long))


def _model(*, reject_tokenization=True):
    from omnivoice.models.omnivoice import OmniVoice

    model = OmniVoice.__new__(OmniVoice)
    model.sampling_rate = 24_000
    model.audio_tokenizer = _Tokenizer(reject=reject_tokenization)
    return model


def test_supplied_transcript_rejects_long_tensor_before_tokenization():
    audio = torch.full((1, 21 * 24_000), 0.1)

    with pytest.raises(ValueError, match=r"\[clone_ref_too_long\].*at most 20 seconds"):
        _model().create_voice_clone_prompt(
            (audio, 24_000),
            ref_text="Transcript supplied by the user.",
            preprocess_prompt=True,
        )


def test_supplied_transcript_rejects_long_file_before_tokenization(tmp_path):
    path = tmp_path / "long-reference.wav"
    sf.write(path, torch.full((21 * 24_000,), 0.1).numpy(), 24_000)

    with pytest.raises(ValueError, match=r"\[clone_ref_too_long\].*at most 20 seconds"):
        _model().create_voice_clone_prompt(
            str(path),
            ref_text="Transcript supplied by the user.",
            preprocess_prompt=True,
        )


def test_missing_transcript_is_safely_trimmed_even_when_preprocessing_is_disabled(monkeypatch):
    model = _model(reject_tokenization=False)
    model._asr_pipe = object()
    model.transcribe = lambda _audio: "Automatically aligned transcript."
    monkeypatch.setattr(
        "omnivoice.models.omnivoice.trim_long_audio",
        lambda audio, sampling_rate, **_kwargs: audio[:, : 15 * sampling_rate],
    )
    audio = torch.full((1, 21 * 24_000), 0.1)

    model.create_voice_clone_prompt(
        (audio, 24_000),
        ref_text=None,
        preprocess_prompt=False,
    )

    assert model.audio_tokenizer.seen_samples == 15 * 24_000


def test_missing_transcript_still_has_a_hard_bound_when_silence_split_cannot_trim(monkeypatch):
    model = _model(reject_tokenization=False)
    model._asr_pipe = object()
    model.transcribe = lambda _audio: "Automatically aligned transcript."
    monkeypatch.setattr(
        "omnivoice.models.omnivoice.trim_long_audio",
        lambda audio, _sampling_rate, **_kwargs: audio,
    )
    audio = torch.full((1, 21 * 24_000), 0.1)

    model.create_voice_clone_prompt((audio, 24_000), ref_text=None)

    assert model.audio_tokenizer.seen_samples == 15 * 24_000


def test_hard_bound_keeps_late_speech_instead_of_cropping_only_silence(monkeypatch):
    model = _model(reject_tokenization=False)
    model._asr_pipe = object()
    model.transcribe = lambda _audio: "Automatically aligned transcript."
    monkeypatch.setattr(
        "omnivoice.models.omnivoice.trim_long_audio",
        lambda audio, _sampling_rate, **_kwargs: audio,
    )
    monkeypatch.setattr(
        "omnivoice.models.omnivoice.remove_silence_safe",
        lambda audio, *_args, **_kwargs: audio,
    )
    audio = torch.zeros((1, 21 * 24_000))
    audio[:, 16 * 24_000 :] = 0.1

    model.create_voice_clone_prompt((audio, 24_000), ref_text=None)

    assert model.audio_tokenizer.seen_samples == 15 * 24_000
    assert model.audio_tokenizer.seen_peak > 0


def test_hard_bound_prefers_speech_over_distant_transient(monkeypatch):
    model = _model(reject_tokenization=False)
    model._asr_pipe = object()
    model.transcribe = lambda _audio: "Automatically aligned transcript."
    monkeypatch.setattr(
        "omnivoice.models.omnivoice.trim_long_audio",
        lambda audio, _sampling_rate, **_kwargs: audio,
    )
    monkeypatch.setattr(
        "omnivoice.models.omnivoice.remove_silence_safe",
        lambda audio, *_args, **_kwargs: audio,
    )
    audio = torch.zeros((1, 31 * 24_000))
    audio[:, 1 * 24_000] = 1.0
    audio[:, 26 * 24_000 :] = 0.01

    model.create_voice_clone_prompt((audio, 24_000), ref_text=None)

    assert model.audio_tokenizer.seen_samples == 15 * 24_000
    # Quiet references are RMS-normalized before cropping. The speech peak is
    # therefore non-zero but remains far below the isolated transient.
    assert 0 < model.audio_tokenizer.seen_peak < 1


def test_real_silence_splitter_does_not_keep_silent_prefix(monkeypatch):
    model = _model(reject_tokenization=False)
    model._asr_pipe = object()
    model.transcribe = lambda _audio: "Automatically aligned transcript."
    monkeypatch.setattr(
        "omnivoice.models.omnivoice.remove_silence_safe",
        lambda audio, *_args, **_kwargs: audio,
    )
    audio = torch.zeros((1, 21 * 24_000))
    audio[:, 16 * 24_000 :] = 0.1

    model.create_voice_clone_prompt((audio, 24_000), ref_text=None)

    assert model.audio_tokenizer.seen_samples == 15 * 24_000
    assert model.audio_tokenizer.seen_peak > 0


def test_real_silence_splitter_ignores_transient_before_late_speech(monkeypatch):
    model = _model(reject_tokenization=False)
    model._asr_pipe = object()
    model.transcribe = lambda _audio: "Automatically aligned transcript."
    monkeypatch.setattr(
        "omnivoice.models.omnivoice.remove_silence_safe",
        lambda audio, *_args, **_kwargs: audio,
    )
    audio = torch.zeros((1, 21 * 24_000))
    audio[:, 1 * 24_000] = 1.0
    audio[:, 16 * 24_000 :] = 0.01

    model.create_voice_clone_prompt((audio, 24_000), ref_text=None)

    assert model.audio_tokenizer.seen_samples == 15 * 24_000
    assert 0 < model.audio_tokenizer.seen_peak < 1


def test_speech_aware_bound_prefers_quiet_voice_over_loud_non_speech(monkeypatch):
    model = _model(reject_tokenization=False)
    model._asr_pipe = object()
    model.transcribe = lambda candidate: (
        "Spoken words." if float(candidate[0].abs().mean()) < 0.05 else ""
    )
    monkeypatch.setattr(
        "omnivoice.models.omnivoice.trim_long_audio",
        lambda audio, _sampling_rate, **_kwargs: audio,
    )
    monkeypatch.setattr(
        "omnivoice.models.omnivoice.remove_silence_safe",
        lambda audio, *_args, **_kwargs: audio,
    )
    audio = torch.full((1, 30 * 24_000), 0.4)
    audio[:, 15 * 24_000 :] = 0.02

    prompt = model.create_voice_clone_prompt((audio, 24_000), ref_text=None)

    assert prompt.ref_text == "Spoken words."
    assert model.audio_tokenizer.seen_peak < 0.1
