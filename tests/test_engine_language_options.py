"""Language metadata must use the same declarations as synthesis guards."""
import pytest
from services import tts_backend as tts

@pytest.mark.parametrize('engine,allowed,rejected', [
    ('kittentts', 'english', 'polish'),
    ('audiocpp', 'chinese', 'polish'),
    ('indextts2', 'spanish', 'polish'),
    ('confucius4-tts', 'french', 'polish'),
])
def test_finite_language_options_without_loading_models(engine, allowed, rejected, monkeypatch):
    monkeypatch.delenv('OMNIVOICE_INDEXTTS_DIR', raising=False)
    options = tts.language_options(engine)
    assert allowed in options
    assert rejected not in options


def test_open_ended_engine_keeps_all_language_options():
    assert tts.language_options('omnivoice') is None


def test_unknown_engine_does_not_break_inventory():
    assert tts.language_options('third-party-unknown') is None


def test_active_engine_inventory_carries_language_choices(monkeypatch):
    from api.routers import engines
    monkeypatch.setattr(tts, 'active_backend_id', lambda: 'kittentts')
    monkeypatch.setattr(tts, 'list_backends', lambda: [
        {'id': 'kittentts', 'available': True},
        {'id': 'omnivoice', 'available': False},
    ])
    response = engines._family_payload('tts', tts)
    assert 'english' in response['backends'][0]['supported_language_names']
    assert 'polish' not in response['backends'][0]['supported_language_names']
    assert 'supported_language_names' not in response['backends'][1]
