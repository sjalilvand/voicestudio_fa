"""#3581: first-run "Continue" stayed disabled after a custom engine setup.

``/setup/status`` required the default OmniVoice weights even when the user
installed and selected another TTS engine in setup's Advanced view. The
requirement now follows the selected engine, and only a ready engine lifts it.
"""
from __future__ import annotations

import pytest

from api.routers.setup import wizard
from services import tts_backend


class _Ready:
    @classmethod
    def is_available(cls):
        return True, "ready"


class _NotReady:
    @classmethod
    def is_available(cls):
        return False, "not installed"


@pytest.fixture
def nothing_cached(monkeypatch):
    monkeypatch.setattr(wizard, "is_cached", lambda repo_id: False)
    monkeypatch.setattr(wizard, "_disk_free_gb", lambda path: 100.0)


def _choose(monkeypatch, engine: str, cls) -> None:
    monkeypatch.setattr(tts_backend, "active_backend_id", lambda: engine)
    monkeypatch.setattr(tts_backend, "get_backend_class", lambda backend_id: cls)


def test_a_ready_custom_engine_lets_first_run_continue(monkeypatch, nothing_cached):
    _choose(monkeypatch, "indextts2", _Ready)
    status = wizard.setup_status()
    assert status["models_ready"] is True
    assert status["missing"] == []


def test_the_default_engine_still_needs_its_model(monkeypatch, nothing_cached):
    _choose(monkeypatch, "omnivoice", _Ready)
    status = wizard.setup_status()
    assert status["models_ready"] is False
    assert [m["repo_id"] for m in status["missing"]] == ["k2-fsa/OmniVoice"]


def test_an_unready_or_unknown_choice_keeps_the_requirement(monkeypatch, nothing_cached):
    _choose(monkeypatch, "indextts2", _NotReady)
    assert wizard.setup_status()["models_ready"] is False

    def unknown(backend_id):
        raise ValueError(backend_id)

    monkeypatch.setattr(tts_backend, "active_backend_id", lambda: "gone")
    monkeypatch.setattr(tts_backend, "get_backend_class", unknown)
    assert wizard.setup_status()["models_ready"] is False
