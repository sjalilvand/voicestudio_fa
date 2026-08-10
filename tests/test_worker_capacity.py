"""Capacity derivation and zombie-slot accounting.

Every rule here exists because the repo already paid for it: #315
(torch.compile thread affinity → silent audio corruption), #567 (concurrent
clone jobs → sticky CUDA abort), and the un-killable GPU thread that made
``_ResilientGpuPool.reset()`` reclaim nothing.
"""
from __future__ import annotations

from worker.capacity import ModelSlot, WorkerCapacity, derive_concurrency

GB = 1024**3


def test_compiled_models_are_always_serial():
    """Thread-local cudagraph state (#315): a second concurrent job produces
    corrupted audio with no exception to catch."""
    assert derive_concurrency(backend="cuda", free_memory_bytes=48 * GB, compiled=True) == 1


def test_apple_unified_memory_is_always_serial():
    """MPS/MLX share memory with everything else the user is running, so a
    number that was safe at config time is not safe at execution time."""
    for backend in ("mps", "mlx", "cpu"):
        assert derive_concurrency(backend=backend, free_memory_bytes=64 * GB) == 1


def test_cuda_concurrency_derives_from_free_memory():
    assert derive_concurrency(backend="cuda", free_memory_bytes=4 * GB) == 1
    assert derive_concurrency(backend="cuda", free_memory_bytes=11 * GB) == 2
    assert derive_concurrency(backend="cuda", free_memory_bytes=24 * GB) == 4


def test_concurrency_is_capped_regardless_of_card_size():
    assert derive_concurrency(backend="cuda", free_memory_bytes=200 * GB) == 4


def test_model_that_does_not_fit_returns_zero():
    """A 4 GB card refusing a 6 GB engine is correct behaviour (#1226), and the
    scheduler must read it as 'send it elsewhere', never as a worker fault."""
    assert derive_concurrency(backend="cuda", free_memory_bytes=4 * GB, min_model_bytes=6 * GB) == 0
    assert derive_concurrency(backend="mps", free_memory_bytes=4 * GB, min_model_bytes=6 * GB) == 0


def test_large_model_reduces_derived_concurrency():
    """A model bigger than the per-job budget takes the space of more than one."""
    small = derive_concurrency(backend="cuda", free_memory_bytes=24 * GB, min_model_bytes=2 * GB)
    large = derive_concurrency(backend="cuda", free_memory_bytes=24 * GB, min_model_bytes=20 * GB)
    assert large < small


# ── Slot accounting ────────────────────────────────────────────────────────


def _cap(**kw) -> WorkerCapacity:
    defaults = dict(worker_id="w1", max_concurrent_tasks=2, backend="cuda")
    defaults.update(kw)
    return WorkerCapacity(**defaults)


def test_reserve_and_release_round_trip():
    cap = _cap()
    assert cap.available_slots == 2
    cap.reserve("indextts", "IndexTTS-2")
    assert cap.available_slots == 1
    cap.release("indextts", "IndexTTS-2")
    assert cap.available_slots == 2


def test_timeout_parks_a_zombie_slot_instead_of_returning_it():
    """A timed-out GPU job cannot be killed — the thread keeps the device.
    Returning the slot early is how a worker gets overcommitted into an OOM."""
    cap = _cap()
    cap.reserve("indextts", "IndexTTS-2")
    cap.release("indextts", "IndexTTS-2", zombie=True)

    assert cap.zombie_tasks == 1
    assert cap.available_slots == 1, "the stuck thread still holds its slot"

    cap.reap_zombie("indextts", "IndexTTS-2")
    assert cap.available_slots == 2


def test_worker_wide_cap_binds_before_per_model_cap():
    """Per-model concurrencies are not independent — they share one VRAM pool."""
    cap = _cap(max_concurrent_tasks=1)
    cap.slots["indextts:IndexTTS-2"] = ModelSlot(
        engine="indextts", model_id="IndexTTS-2", derived_concurrency=4
    )
    cap.reserve("indextts", "IndexTTS-2")
    assert cap.can_accept("indextts", "IndexTTS-2") is False


def test_unknown_model_defers_to_the_worker():
    """The worker's accept/reject is authoritative; the scheduler's view is
    advisory and may be stale."""
    cap = _cap()
    assert cap.can_accept("brand-new-engine", "whatever") is True


def test_snapshot_is_absolute_not_a_delta():
    """Out-of-order deltas corrupt the count permanently after a reconnect."""
    cap = _cap()
    cap.reserve("indextts", "IndexTTS-2")
    cap.reserve("indextts", "IndexTTS-2")
    cap.apply_snapshot(active_tasks=0, available_slots=2, resident_models={"indextts:IndexTTS-2"})

    assert cap.active_tasks == 0
    assert cap.available_slots == 2


def test_residency_is_visible_to_the_scheduler():
    """Warm vs cold is the dominant latency term — 8s versus minutes."""
    cap = _cap(resident_models={"indextts:IndexTTS-2"})
    assert cap.is_resident("indextts", "IndexTTS-2") is True
    assert cap.is_resident("cosyvoice", "CosyVoice2") is False


def test_release_never_underflows():
    cap = _cap()
    cap.release("indextts", "IndexTTS-2")
    cap.reap_zombie("indextts", "IndexTTS-2")
    assert cap.active_tasks == 0
    assert cap.zombie_tasks == 0
