from __future__ import annotations

import asyncio
import importlib
import sys
import types
from unittest.mock import Mock

import pytest


@pytest.fixture
def manager(monkeypatch):
    for name in ("core.config", "services.model_manager"):
        module = sys.modules.get(name)
        if module is not None and not getattr(module, "__file__", None):
            sys.modules.pop(name, None)
    module = importlib.import_module("services.model_manager")
    module._torch = None
    module._OmniVoice = None
    module.model = None
    module._shutting_down.clear()
    monkeypatch.setenv("OMNIVOICE_MODEL", "example/test-checkpoint")
    return module


def test_preload_flag_recognises_each_enabled_spelling(manager, monkeypatch):
    observed = {}
    for spelling in ("on", " YES ", "TRUE", "1", "true"):
        monkeypatch.setenv("OMNIVOICE_PRELOAD_TTS_ASR", spelling)
        observed[spelling] = manager.should_preload_tts_asr()
    assert observed == dict.fromkeys(observed, True)


def test_preload_flag_defaults_off_and_rejects_zero(manager, monkeypatch):
    monkeypatch.delenv("OMNIVOICE_PRELOAD_TTS_ASR", raising=False)
    assert manager.should_preload_tts_asr() is False
    monkeypatch.setenv("OMNIVOICE_PRELOAD_TTS_ASR", "0")
    assert manager.should_preload_tts_asr() is False


def _configure_sync_load(manager, monkeypatch):
    load_asr = Mock(name="load_asr_model")
    loaded = types.SimpleNamespace(llm=object(), load_asr_model=load_asr)
    calls = []

    def construct_model(*args, **kwargs):
        calls.append((args, kwargs))
        return loaded

    fake_torch = types.SimpleNamespace(float16="half", float32="full")
    monkeypatch.setattr(manager, "_lazy_torch", lambda: fake_torch)
    monkeypatch.setattr(
        manager,
        "_lazy_omnivoice",
        lambda: types.SimpleNamespace(from_pretrained=construct_model),
    )
    monkeypatch.setattr(manager, "get_best_device", lambda: "cuda")
    monkeypatch.setattr(manager, "_preflight_truncated_weights", lambda _checkpoint: None)
    return loaded, calls


def test_sync_load_keeps_asr_out_of_from_pretrained_by_default(manager, monkeypatch):
    monkeypatch.delenv("OMNIVOICE_PRELOAD_TTS_ASR", raising=False)
    loaded, calls = _configure_sync_load(manager, monkeypatch)

    result = manager._load_model_sync()

    assert result is loaded
    assert calls == [(('example/test-checkpoint',), {
        "device_map": "cuda", "dtype": "half", "load_asr": False,
    })]
    assert result.llm is not None
    assert result._voicestudio_checkpoint == "example/test-checkpoint"
    assert result._voicestudio_loaded_at.endswith("Z")
    loaded.load_asr_model.assert_not_called()


def test_opt_in_loads_asr_after_tts(manager, monkeypatch):
    monkeypatch.setenv("OMNIVOICE_PRELOAD_TTS_ASR", "yes")
    loaded, calls = _configure_sync_load(manager, monkeypatch)

    manager._load_model_sync()

    assert calls[0][1]["load_asr"] is False
    loaded.load_asr_model.assert_called_once_with()


def test_checkpoint_resolution_preserves_test_sentinel_and_repairs_engine_id(
    manager, monkeypatch
):
    monkeypatch.setenv("OMNIVOICE_MODEL", "test")
    assert manager.resolve_omnivoice_checkpoint() == "test"
    monkeypatch.setenv("OMNIVOICE_MODEL", "omnivoice")
    assert manager.resolve_omnivoice_checkpoint() == manager._DEFAULT_OMNIVOICE_CHECKPOINT


def _configure_preload(manager, monkeypatch, *, cached):
    monkeypatch.setattr(
        "core.device_caps.detect_host_caps",
        lambda: types.SimpleNamespace(family="cpu"),
    )
    monkeypatch.setattr(manager, "_ensure_omnivoice_licence", lambda: None)
    monkeypatch.setattr(manager, "_checkpoint_in_local_cache", lambda _checkpoint: cached)


def test_preload_does_not_load_an_uncached_checkpoint(manager, monkeypatch):
    _configure_preload(manager, monkeypatch, cached=False)
    calls = []

    async def record_load():
        calls.append(True)

    monkeypatch.setattr(manager, "_load_model_with_timeout", record_load)
    asyncio.run(manager.preload_model())
    assert calls == []
    assert manager.model is None


def test_preload_stores_locally_cached_model(manager, monkeypatch):
    _configure_preload(manager, monkeypatch, cached=True)
    loaded = object()

    async def load():
        return loaded

    monkeypatch.setattr(manager, "_load_model_with_timeout", load)
    asyncio.run(manager.preload_model())
    assert manager.model is loaded
