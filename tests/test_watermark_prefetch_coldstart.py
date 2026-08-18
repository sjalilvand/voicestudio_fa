"""Background warm-up + thread safety for the AudioSeal watermark models.

The 2026-08-17 cold-start report on a macOS deployment: the first
``mark_synthetic`` serialized the audioseal import + generator load (~42 s on
a cold filesystem) INSIDE the first synthesis, and a 90 s client timeout
missed the audio by 3 s. The generator now warms on a background thread
during startup; because that thread races the first embed, the lazy getters
must be thread-safe — exactly one load, no torn state.
"""
from __future__ import annotations

import sys
import threading
import types
from types import SimpleNamespace

import pytest

from services import watermark


@pytest.fixture(autouse=True)
def _reset_models(monkeypatch):
    # Reset ALL lifecycle globals (CodeRabbit, PR #1577): a stale warm-up
    # stamp or availability cache from a prior test changes this test's
    # conditions.
    watermark._generator = None
    watermark._detector = None
    watermark._last_used = 0.0
    watermark._prefetched_unused = False
    monkeypatch.setattr(watermark, "_audioseal_available", None, raising=False)
    yield
    watermark._generator = None
    watermark._detector = None
    watermark._last_used = 0.0
    watermark._prefetched_unused = False


def _fake_audioseal(monkeypatch, load_s: float) -> list[int]:
    """Install a fake ``audioseal`` module whose load blocks ``load_s`` and
    records every invocation. The block is what makes a missing lock fail
    reliably instead of winning the interleaving lottery."""
    calls: list[int] = []
    import time

    def _slow_load(name):
        calls.append(1)
        time.sleep(load_s)
        return SimpleNamespace(eval=lambda: None)

    fake = types.ModuleType("audioseal")
    fake.AudioSeal = SimpleNamespace(load_generator=_slow_load)
    monkeypatch.setitem(sys.modules, "audioseal", fake)
    return calls


def test_get_generator_loads_exactly_once_under_concurrency(monkeypatch):
    """A background prefetch thread + the first embed race the lazy load;
    both must share ONE generator build, not one each."""
    calls = _fake_audioseal(monkeypatch, load_s=0.05)

    results = []
    errors = []

    def _hit():
        try:
            results.append(watermark._get_generator())
        except Exception as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    threads = [threading.Thread(target=_hit) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors
    assert calls == [1], f"load_generator ran {len(calls)}x; the lazy load races"
    assert all(g is results[0] for g in results)


def test_prefetch_generator_loads_when_watermarking_is_on(monkeypatch):
    """prefetch_generator() must build the generator eagerly (the startup
    warm-up path) while the pref is enabled and audioseal is importable."""
    calls = _fake_audioseal(monkeypatch, load_s=0)
    monkeypatch.setattr(watermark, "is_enabled", lambda: True)

    watermark.prefetch_generator()

    assert calls == [1]
    assert watermark._generator is not None


def test_prefetch_generator_no_ops_when_disabled_or_absent(monkeypatch):
    """Pref disabled, or audioseal not installed: the warm-up must touch
    nothing — no import attempts, no model, no exception."""
    calls = _fake_audioseal(monkeypatch, load_s=0)
    monkeypatch.setattr(watermark, "is_enabled", lambda: False)
    watermark.prefetch_generator()
    assert calls == []
    assert watermark._generator is None

    monkeypatch.setattr(watermark, "is_enabled", lambda: True)
    monkeypatch.setattr(watermark, "_check_available", lambda: False)
    watermark.prefetch_generator()
    assert calls == []
    assert watermark._generator is None


def test_prefetch_generator_degrades_silently_on_failure(monkeypatch):
    """A failed warm-up must never take the backend down or wedge the lazy
    path: log, leave _generator None; the first embed retries inline."""
    monkeypatch.setattr(watermark, "is_enabled", lambda: True)
    monkeypatch.setattr(watermark, "_check_available", lambda: True)

    def _boom():
        raise RuntimeError("hub exploded (test)")

    monkeypatch.setattr(watermark, "_get_generator", _boom)
    watermark.prefetch_generator()  # must not raise
    assert watermark._generator is None


def test_detector_load_is_not_blocked_by_a_generator_prefetch(monkeypatch):
    """Per-model locks (review finding): a ~42s generator build in the
    prefetch thread must not stall an unrelated detector load — with the old
    single shared lock, _get_detector queued behind the whole build."""
    gen_started = threading.Event()
    gen_release = threading.Event()
    det_done = threading.Event()

    fake = types.ModuleType("audioseal")

    def _slow_gen(name):
        gen_started.set()
        gen_release.wait(10)
        return SimpleNamespace(eval=lambda: None)

    def _fast_det(name):
        det_done.set()
        return SimpleNamespace(eval=lambda: None)

    fake.AudioSeal = SimpleNamespace(load_generator=_slow_gen, load_detector=_fast_det)
    monkeypatch.setitem(sys.modules, "audioseal", fake)

    t = threading.Thread(target=watermark._get_generator)
    t.start()
    assert gen_started.wait(5)
    det = watermark._get_detector()  # must NOT queue behind the generator build
    assert det_done.wait(1), "detector load blocked behind the generator load"
    gen_release.set()
    t.join(timeout=10)


def test_watermark_pool_rebuilds_after_shutdown_drain():
    """The lifespan shutdown drains the watermark pool; a process that keeps
    running afterwards (the test suite) must get a FRESH pool on next use,
    not "cannot schedule new futures after shutdown" (CI, PR #1577)."""
    from services.model_manager import get_watermark_pool, shutdown_watermark_pool

    pool_before = get_watermark_pool()
    shutdown_watermark_pool()
    with pytest.raises(RuntimeError):
        # The drained pool refuses new work…
        pool_before.submit(lambda: None).result(timeout=5)
    # …but the next getter hands out a live replacement.
    assert get_watermark_pool().submit(lambda: "ok").result(timeout=5) == "ok"
    # Clean up the replacement so later tests start from a fresh pool too.
    shutdown_watermark_pool()


def test_prefetched_model_gets_one_extra_idle_window(monkeypatch):
    """Review finding: the reaper freed the prefetch-warmed, never-used
    generator at the first idle tick, re-imposing the cold start the prefetch
    exists to hide. It now survives ONE extra window; real use clears the
    grace entirely.

    Each phase re-establishes its module state IMMEDIATELY before its
    release_idle_models call and passes an explicit far-future ``now=``: a
    leaked idle reaper (a test lifespan that exits without shutdown keeps
    idle_worker running) mutates these same globals from another thread, and
    re-stamping _last_used mid-test made the real-assertions flake on CI.
    With preconditions set adjacent to each call and now pinned, an
    interleaved tick cannot change the outcome.
    """
    import time

    # Full isolation from a leaked idle reaper (idle_worker resolves
    # watermark.release_idle_models per call): divert it to a no-op for the
    # duration of this test, and call the real function via the saved ref.
    real_release = watermark.release_idle_models
    # The test owns the reaper's decisions for its duration.
    monkeypatch.setattr(watermark, "release_idle_models", lambda *a, **k: False)

    far_future = time.monotonic() + 1_000_000

    def _given(generator_set: bool, grace: bool):
        watermark._generator = SimpleNamespace(eval=lambda: None) if generator_set else None
        watermark._prefetched_unused = grace
        watermark._last_used = 0.0

    # First reaper pass on a prefetched-never-used model: grace, model kept.
    _given(generator_set=True, grace=True)
    assert real_release(900, now=far_future) is False
    # Second pass: grace consumed, model released.
    _given(generator_set=True, grace=False)
    assert real_release(900, now=far_future) is True
    # After grace was consumed, an idle model with no models at all is a no-op.
    _given(generator_set=False, grace=False)
    assert real_release(900, now=far_future) is False

    # Real use clears the grace: embed (even a failing one) resets the flag,
    # so the next reaper pass releases without a second window.
    import torch as _torch
    monkeypatch.setattr(watermark, "is_enabled", lambda: True)
    monkeypatch.setattr(watermark, "_check_available", lambda: True)
    watermark._generator = SimpleNamespace(eval=lambda: None)
    watermark._prefetched_unused = True
    watermark.embed_watermark(_torch.zeros(1, 2400), 24000)
    # The embed call itself must have cleared the grace — assert it, don't
    # re-establish it, or a failing embed would pass unnoticed.
    assert watermark._prefetched_unused is False
    assert real_release(900, now=far_future) is True
