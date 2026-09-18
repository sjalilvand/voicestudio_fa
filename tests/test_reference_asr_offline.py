"""Transcript-free cloning must never implicitly download a second ASR (#2116)."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import torch


def _model():
    from omnivoice.models.omnivoice import OmniVoice
    model = OmniVoice.__new__(OmniVoice)
    model.sampling_rate = 24_000
    model._asr_pipe = None
    model.audio_tokenizer = SimpleNamespace(
        config=SimpleNamespace(hop_length=320), device="cpu",
        encode=lambda _: SimpleNamespace(audio_codes=torch.zeros((1, 1, 1))),
    )
    model.transcribe = lambda _: "Words from the reference."
    return model


@pytest.mark.parametrize("seconds", [1, 21])
def test_missing_implicit_asr_never_calls_network_capable_loader(monkeypatch, seconds):
    from huggingface_hub.errors import LocalEntryNotFoundError
    model = _model()
    loader = Mock(side_effect=AssertionError("implicit network-capable ASR load"))
    model.load_asr_model = loader
    lookup = Mock(side_effect=LocalEntryNotFoundError("not cached"))
    monkeypatch.setattr("huggingface_hub.snapshot_download", lookup)
    with pytest.raises(ValueError, match="reference transcript"):
        model.create_voice_clone_prompt(
            (torch.full((1, seconds * 24_000), 0.1), 24_000),
            preprocess_prompt=False,
        )
    loader.assert_not_called()
    lookup.assert_called_once_with("openai/whisper-large-v3-turbo", local_files_only=True)


@pytest.mark.parametrize("seconds", [1, 21])
def test_implicit_asr_loads_only_the_resolved_local_snapshot(monkeypatch, tmp_path, seconds):
    model = _model()
    snapshot = tmp_path / "cached-whisper"
    snapshot.mkdir()
    lookup = Mock(return_value=str(snapshot))
    monkeypatch.setattr("huggingface_hub.snapshot_download", lookup)

    def load(*, model_name):
        assert model_name == str(snapshot)
        model._asr_pipe = object()

    model.load_asr_model = Mock(side_effect=load)
    prompt = model.create_voice_clone_prompt(
        (torch.full((1, seconds * 24_000), 0.1), 24_000),
        preprocess_prompt=False,
    )
    assert prompt.ref_text == "Words from the reference."
    model.load_asr_model.assert_called_once_with(model_name=str(snapshot))
    lookup.assert_called_once_with("openai/whisper-large-v3-turbo", local_files_only=True)


def test_supplied_transcript_does_not_look_for_asr(monkeypatch):
    model = _model()
    lookup = Mock(side_effect=AssertionError("ASR lookup not needed"))
    monkeypatch.setattr("huggingface_hub.snapshot_download", lookup)
    prompt = model.create_voice_clone_prompt(
        (torch.full((1, 24_000), 0.1), 24_000),
        ref_text="Supplied words.", preprocess_prompt=False,
    )
    assert prompt.ref_text == "Supplied words."
    lookup.assert_not_called()
