"""Pause fill: digital silence (default) or room tone (#3611).

Cloned speech carries a quiet noise floor; zeros between ``[pause]`` spans
made the background cut out at every marker. Room tone fills the gap with
noise shaped like the take's own quietest frames, with fades into the
neighbouring lines, and falls back to silence when there is no usable floor.
"""
import numpy as np
import pytest
import torch

from services import audio_dsp
from services.audio_dsp import fill_gaps

SR = 24000


def _take(seconds=1.0, floor_db=-53.0, seed=0):
    """Speech-like bursts over a steady noise floor, shape (1, n)."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    floor = rng.standard_normal(n) * 10 ** (floor_db / 20)
    t = np.arange(n) / SR
    speech = 0.3 * np.sin(2 * np.pi * 220 * t) * (np.sin(2 * np.pi * 3 * t) > 0)
    return torch.tensor(floor + speech, dtype=torch.float32).unsqueeze(0)


def _db(x):
    x = np.asarray(x, dtype=np.float64)
    return 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-12)


@pytest.fixture
def prefs_store(monkeypatch):
    from core import prefs

    store: dict = {}
    monkeypatch.delenv(audio_dsp.PAUSE_FILL_ENV, raising=False)
    monkeypatch.setattr(prefs, "get", lambda key, default=None: store.get(key, default))
    monkeypatch.setattr(prefs, "set_", lambda key, value: store.__setitem__(key, value))
    return store


def test_silence_stays_the_default(prefs_store):
    a, b = _take(), _take(seed=1)
    parts = fill_gaps([("a", a), ("s", 1200), ("a", b)], SR)
    assert torch.equal(parts[0], a) and torch.equal(parts[2], b)
    assert parts[1].shape == (1, 1200) and not parts[1].any()


def test_room_tone_sits_at_the_takes_floor(prefs_store):
    prefs_store[audio_dsp.PAUSE_FILL_PREF] = "room_tone"
    parts = fill_gaps([("a", _take()), ("s", SR), ("a", _take(seed=1))], SR)
    gap = parts[1].numpy()
    assert gap.shape == (1, SR)
    assert not np.any(gap == 0.0)
    assert abs(_db(gap) - (-53.0)) < 4.0  # the floor, not silence, not speech


def test_room_tone_fades_into_the_neighbouring_lines():
    a, b = _take(), _take(seed=1)
    parts = fill_gaps([("a", a), ("s", SR // 2), ("a", b)], SR, "room_tone")
    fade = int(SR * 0.04)
    # Only the last / first 40 ms of the lines change; the callers' tensors are untouched.
    assert torch.equal(parts[0][..., :-fade], a[..., :-fade])
    assert not torch.equal(parts[0][..., -fade:], a[..., -fade:])
    assert torch.equal(parts[2][..., fade:], b[..., fade:])
    assert torch.equal(a, _take()) and torch.equal(b, _take(seed=1))
    assert sum(p.shape[-1] for p in parts) == a.shape[-1] + SR // 2 + b.shape[-1]


def test_room_tone_is_reproducible():
    items = [("a", _take()), ("s", 4000), ("a", _take(seed=1))]
    first = fill_gaps(items, SR, "room_tone")
    second = fill_gaps(items, SR, "room_tone")
    assert all(torch.equal(x, y) for x, y in zip(first, second))


def test_no_usable_floor_falls_back_to_silence():
    clean = torch.zeros(1, SR)
    clean[0, : SR // 2] = 0.5  # loud, then digital silence: no quiet floor
    parts = fill_gaps([("a", clean), ("s", 1000), ("a", clean)], SR, "room_tone")
    assert not parts[1].any()


def test_render_with_pauses_uses_room_tone(prefs_store):
    from api.routers.generation import _render_with_pauses

    take = _take()
    out = _render_with_pauses(lambda text: take.clone(), [("a", 500), ("b", 0)], SR,
                              pause_fill="room_tone")
    gap = out[0, SR:SR + int(SR * 0.5)].numpy()
    assert out.shape == (1, 2 * SR + SR // 2)
    assert not np.any(gap == 0.0)
    silent = _render_with_pauses(lambda text: take.clone(), [("a", 500), ("b", 0)], SR)
    assert not silent[0, SR:SR + int(SR * 0.5)].any()


def test_audiobook_line_and_paragraph_gaps_use_room_tone(prefs_store):
    from services.audiobook import Span, synthesize_chapter

    prefs_store[audio_dsp.PAUSE_FILL_PREF] = "room_tone"
    spans = [Span(voice_id=None, text="one", pause_ms_after=500),
             Span(voice_id=None, text="two", pause_ms_after=0)]
    audio, _dur = synthesize_chapter(spans, lambda text, voice, speed: _take(), SR)
    gap = audio[..., SR + int(SR * 0.05):SR + int(SR * 0.45)].numpy()
    assert not np.any(gap == 0.0)


def test_env_overrides_settings_and_bad_values_mean_silence(prefs_store, monkeypatch):
    prefs_store[audio_dsp.PAUSE_FILL_PREF] = "room_tone"
    assert audio_dsp.pause_fill_mode() == "room_tone"
    monkeypatch.setenv(audio_dsp.PAUSE_FILL_ENV, "silence")
    assert audio_dsp.pause_fill_mode() == "silence"
    monkeypatch.setenv(audio_dsp.PAUSE_FILL_ENV, "pink-noise")
    assert audio_dsp.pause_fill_mode() == "silence"


def test_settings_route_round_trips(prefs_store):
    from api.routers import settings

    assert settings.get_pause_fill()["mode"] == "silence"
    saved = settings.set_pause_fill(settings._PauseFillBody(mode="room_tone"))
    assert saved == {"mode": "room_tone", "env_pinned": False,
                     "choices": ["silence", "room_tone"]}
    with pytest.raises(ValueError):
        settings._PauseFillBody(mode="pink-noise")


def test_room_tone_gets_its_own_audiobook_cache_slot(prefs_store, tmp_path):
    """A chapter rendered with silence must not replay once room tone is on,
    and the default keeps today's key so existing caches still hit."""
    import os

    from api.routers.audiobook import _render_chapter_cached
    from services.audiobook import Chapter, Span

    def key(sub):
        ch = Chapter(title="C", spans=[Span(voice_id=None, text="hello", pause_ms_after=300),
                                       Span(voice_id=None, text="there", pause_ms_after=0)])
        wav, *_ = _render_chapter_cached(
            ch, lambda text, vid, speed=None: _take(0.2), SR, "eng",
            lambda vid: {"ref_audio": None, "ref_text": None, "instruct": None, "seed": None},
            str(tmp_path / sub), None, None, None)
        return os.path.basename(wav)

    silent = key("a")
    assert key("b") == silent
    prefs_store[audio_dsp.PAUSE_FILL_PREF] = "room_tone"
    assert key("c") != silent
