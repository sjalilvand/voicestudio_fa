"""Worker capacity — derived, never declared.

The original goal doc let a user configure "Whisper: concurrency = 4, large TTS
model: concurrency = 1". This repo's own history says that is unsafe:

  * compiled inference is pinned to a single thread because torch.compile's
    cudagraph state is thread-local (#315) — a second concurrent job on a
    compiled model produces *silently corrupted audio*, with no exception to
    catch and nothing for a reliability score to detect;
  * two concurrent clone jobs on an 8 GB card produced a sticky CUDA
    illegal-memory-access that aborted the whole process (#567), which is why
    ``gpu_queue`` is a deliberately serial single lane;
  * Apple's unified memory means "GPU memory" is shared with everything else
    the user is running, so a number that was safe at configuration time is not
    safe at execution time.

So capacity is computed from what the machine has *right now*, clamped by
device family, and the worker's own accept/reject is authoritative — the
scheduler's view is only ever advisory.

One more rule the repo learned the hard way: a timed-out GPU job cannot be
killed. The thread keeps the device until it finishes on its own
(``_ResilientGpuPool.reset()`` reclaims nothing). So a timeout must NOT return
the slot; the slot stays occupied by a zombie until the worker confirms the
thread exited. Returning it early is how a worker gets overcommitted into an
OOM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Per-job VRAM budget. Mirrors the figure model_manager uses when sizing its
# GPU worker pool; deliberately conservative because exceeding it does not
# degrade gracefully, it aborts the process.
_VRAM_PER_JOB_BYTES = 5 * 1024**3

# Device families where concurrency above 1 is never derived:
#   mps/mlx — unified memory, shared with the user's other apps
#   cpu     — oversubscription just thrashes
_ALWAYS_SERIAL = frozenset({"mps", "mlx", "cpu", ""})

# Absolute ceiling regardless of how much memory a card reports. Beyond this
# the bottleneck stops being VRAM and starts being scheduler overhead and
# host-side I/O contention.
_MAX_DERIVED = 4


def derive_concurrency(
    *,
    backend: str,
    free_memory_bytes: int,
    min_model_bytes: int = 0,
    compiled: bool = False,
) -> int:
    """How many jobs of this model may run at once on this worker.

    Returns 0 when the model cannot run here at all — a capability mismatch,
    which the scheduler must treat as "send it elsewhere", never as a worker
    fault.
    """
    family = (backend or "").strip().lower()
    if min_model_bytes and free_memory_bytes < min_model_bytes:
        return 0
    if compiled:
        # Thread-affinity pinning (#315). One job, always.
        return 1
    if family in _ALWAYS_SERIAL:
        return 1 if (not min_model_bytes or free_memory_bytes >= min_model_bytes) else 0
    budget = max(min_model_bytes, _VRAM_PER_JOB_BYTES)
    if budget <= 0:
        return 1
    return max(1, min(_MAX_DERIVED, int(free_memory_bytes // budget)))


@dataclass
class ModelSlot:
    """Capacity bookkeeping for one (worker, model) pair."""

    engine: str
    model_id: str
    derived_concurrency: int = 1
    active: int = 0
    # Slots held by jobs that timed out but whose GPU thread has not exited.
    # Not available, not counted as active work, not returnable until the
    # worker says the thread is gone.
    zombie: int = 0

    @property
    def available(self) -> int:
        return max(0, self.derived_concurrency - self.active - self.zombie)


@dataclass
class WorkerCapacity:
    """Live capacity snapshot for one worker.

    Absolute values only — never deltas. Per-stream FIFO does not survive a
    reconnect, so a delta that arrives out of order corrupts the count
    permanently.
    """

    worker_id: str
    max_concurrent_tasks: int = 1
    active_tasks: int = 0
    zombie_tasks: int = 0
    free_memory_bytes: int = 0
    backend: str = ""
    resident_models: set[str] = field(default_factory=set)
    slots: dict[str, ModelSlot] = field(default_factory=dict)

    @staticmethod
    def slot_key(engine: str, model_id: str) -> str:
        return f"{engine}:{model_id}"

    @property
    def available_slots(self) -> int:
        """Worker-wide availability. The binding constraint is whichever of
        the worker-wide and per-model caps is smaller — they are not
        independent, because every model draws on the same VRAM."""
        return max(0, self.max_concurrent_tasks - self.active_tasks - self.zombie_tasks)

    def slot_for(self, engine: str, model_id: str) -> Optional[ModelSlot]:
        return self.slots.get(self.slot_key(engine, model_id))

    def can_accept(self, engine: str, model_id: str) -> bool:
        if self.available_slots <= 0:
            return False
        slot = self.slot_for(engine, model_id)
        if slot is None:
            # Unknown model on a worker with room: the worker decides. Its
            # reject is authoritative and penalty-free.
            return True
        return slot.available > 0

    def is_resident(self, engine: str, model_id: str) -> bool:
        """Warm models are the dominant latency term — 8s versus minutes."""
        return self.slot_key(engine, model_id) in self.resident_models or model_id in self.resident_models

    def reserve(self, engine: str, model_id: str) -> None:
        self.active_tasks += 1
        slot = self.slots.setdefault(
            self.slot_key(engine, model_id), ModelSlot(engine=engine, model_id=model_id)
        )
        slot.active += 1

    def release(self, engine: str, model_id: str, *, zombie: bool = False) -> None:
        """Return a slot. ``zombie=True`` parks it instead: the task is over
        but the GPU thread is not, so the capacity is still gone."""
        slot = self.slots.get(self.slot_key(engine, model_id))
        if slot is not None and slot.active > 0:
            slot.active -= 1
            if zombie:
                slot.zombie += 1
        if self.active_tasks > 0:
            self.active_tasks -= 1
        if zombie:
            self.zombie_tasks += 1

    def reap_zombie(self, engine: str, model_id: str) -> None:
        """The worker confirmed the stuck thread exited. Capacity returns."""
        slot = self.slots.get(self.slot_key(engine, model_id))
        if slot is not None and slot.zombie > 0:
            slot.zombie -= 1
        if self.zombie_tasks > 0:
            self.zombie_tasks -= 1

    def apply_snapshot(
        self,
        *,
        active_tasks: int,
        available_slots: int,
        resident_models: Optional[set[str]] = None,
        free_memory_bytes: Optional[int] = None,
    ) -> None:
        """Adopt a heartbeat snapshot. The worker is the source of truth for
        what it is actually running."""
        self.active_tasks = max(0, active_tasks)
        self.max_concurrent_tasks = max(
            self.max_concurrent_tasks, active_tasks + max(0, available_slots)
        )
        if resident_models is not None:
            self.resident_models = set(resident_models)
        if free_memory_bytes is not None:
            self.free_memory_bytes = free_memory_bytes

    def to_dict(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "active_tasks": self.active_tasks,
            "zombie_tasks": self.zombie_tasks,
            "available_slots": self.available_slots,
            "resident_models": sorted(self.resident_models),
        }


__all__ = ["ModelSlot", "WorkerCapacity", "derive_concurrency"]
