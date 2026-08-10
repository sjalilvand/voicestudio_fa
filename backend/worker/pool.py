"""Live worker state.

Everything here is in-memory and rebuilt from reconnection, by design: sessions,
capacity snapshots, latency, breaker state. A desktop control plane restarts
constantly, and none of this is worth persisting when the worker itself will
tell us the truth the moment it reconnects.

What the pool owns is the *current* picture — who is connected, on which epoch,
with what free capacity and which models warm. What it deliberately does not
own is anything durable (``registry``) or any scheduling policy
(``scheduler``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterator, Optional

from worker.breaker import BreakerRegistry
from worker.capacity import WorkerCapacity, derive_concurrency
from worker.clock import resolve
from worker.identity import Session
from worker.registry import RemoteWorker

logger = logging.getLogger("omnivoice.worker")

# A worker that has not been heard from in this long is treated as gone even if
# the socket has not reported it. Half-open TCP through an expired CGNAT
# mapping looks identical to a healthy idle connection until you ask.
_HEARTBEAT_MISS_SECONDS = 90.0


@dataclass
class ConnectedWorker:
    """One live worker session."""

    record: RemoteWorker
    session: Session
    epoch: int
    capacity: WorkerCapacity
    connected_at: float
    last_heartbeat_at: float
    latency_ms: float = 0.0
    draining: bool = False
    # Attempt ids this worker claims to be running. Rebuilt on every reconnect
    # from its own report, never inferred.
    in_flight: set[str] = field(default_factory=set)

    @property
    def worker_id(self) -> str:
        return self.record.id

    @property
    def name(self) -> str:
        return self.record.name

    def stale(self, *, now: Optional[float] = None) -> bool:
        return resolve(now) - self.last_heartbeat_at > _HEARTBEAT_MISS_SECONDS

    def supports(self, engine: str, model_id: str, operation: str) -> bool:
        """Can this worker run this work at all?

        ``supported`` alone is not enough — an engine whose weights are not on
        disk cannot start without a download, and one that is not installed
        cannot start at all. Both are capability mismatches, not failures.
        """
        for cap in self.record.capabilities:
            if cap.get("engine") != engine:
                continue
            if model_id and cap.get("model_id") not in (model_id, "", None):
                continue
            if operation and operation not in (cap.get("operations") or [operation]):
                continue
            return bool(cap.get("supported")) and bool(cap.get("installed", True))
        return False

    def is_warm(self, engine: str, model_id: str) -> bool:
        return self.capacity.is_resident(engine, model_id)

    def to_dict(self, *, now: Optional[float] = None) -> dict:
        return {
            **self.record.to_dict(),
            "connected": True,
            "draining": self.draining,
            "latency_ms": round(self.latency_ms, 1),
            "active_tasks": self.capacity.active_tasks,
            "available_slots": self.capacity.available_slots,
            "resident_models": sorted(self.capacity.resident_models),
            "stale": self.stale(now=now),
        }


class WorkerPool:
    """The set of workers currently connected, plus their breakers."""

    def __init__(self) -> None:
        self._connected: dict[str, ConnectedWorker] = {}
        self.breakers = BreakerRegistry()

    # ── Membership ────────────────────────────────────────────────────────

    def connect(
        self,
        record: RemoteWorker,
        *,
        session: Session,
        epoch: int,
        max_concurrent_tasks: int = 1,
        backend: str = "",
        in_flight: Optional[set[str]] = None,
        now: Optional[float] = None,
    ) -> ConnectedWorker:
        """Register a live session, replacing any previous one.

        Newest epoch wins, unconditionally. Two sessions for one worker is the
        race that delivers two accepts for a single assignment, so the old one
        is dropped rather than merged.
        """
        stamp = resolve(now)
        previous = self._connected.get(record.id)
        if previous is not None and previous.epoch > epoch:
            raise ValueError(
                f"refusing to install session epoch {epoch} over newer epoch {previous.epoch}"
            )
        worker = ConnectedWorker(
            record=record,
            session=session,
            epoch=epoch,
            capacity=WorkerCapacity(
                worker_id=record.id,
                max_concurrent_tasks=max(1, max_concurrent_tasks),
                backend=backend,
            ),
            connected_at=stamp,
            last_heartbeat_at=stamp,
            in_flight=set(in_flight or set()),
        )
        self._connected[record.id] = worker
        self.breakers.note_worker(record.id)
        if previous is not None:
            logger.info("Worker %s reconnected (epoch %d → %d)", record.name, previous.epoch, epoch)
        return worker

    def disconnect(self, worker_id: str) -> Optional[ConnectedWorker]:
        return self._connected.pop(worker_id, None)

    def get(self, worker_id: str) -> Optional[ConnectedWorker]:
        return self._connected.get(worker_id)

    def __iter__(self) -> Iterator[ConnectedWorker]:
        return iter(list(self._connected.values()))

    def __len__(self) -> int:
        return len(self._connected)

    @property
    def connected_ids(self) -> set[str]:
        return set(self._connected)

    # ── Session validity ──────────────────────────────────────────────────

    def valid_epoch(self, worker_id: str, epoch: int) -> bool:
        """Fence: is this message from the session we currently believe in?"""
        worker = self._connected.get(worker_id)
        return worker is not None and worker.epoch == epoch

    # ── Heartbeats ────────────────────────────────────────────────────────

    def heartbeat(
        self,
        worker_id: str,
        *,
        active_tasks: int,
        available_slots: int,
        resident_models: Optional[set[str]] = None,
        free_memory_bytes: Optional[int] = None,
        latency_ms: Optional[float] = None,
        now: Optional[float] = None,
    ) -> Optional[ConnectedWorker]:
        worker = self._connected.get(worker_id)
        if worker is None:
            return None
        worker.last_heartbeat_at = resolve(now)
        if latency_ms is not None:
            worker.latency_ms = latency_ms
        worker.capacity.apply_snapshot(
            active_tasks=active_tasks,
            available_slots=available_slots,
            resident_models=resident_models,
            free_memory_bytes=free_memory_bytes,
        )
        return worker

    def apply_capabilities(self, worker_id: str, capabilities: list[dict]) -> None:
        """Refresh what a worker can run, and re-derive its per-model slots."""
        worker = self._connected.get(worker_id)
        if worker is None:
            return
        worker.record.capabilities = capabilities
        for cap in capabilities:
            key = WorkerCapacity.slot_key(cap.get("engine", ""), cap.get("model_id", ""))
            slot = worker.capacity.slots.get(key)
            declared = int(cap.get("derived_concurrency") or 0)
            if declared <= 0:
                declared = derive_concurrency(
                    backend=cap.get("backend", worker.capacity.backend),
                    free_memory_bytes=int(cap.get("free_memory_bytes") or 0),
                    min_model_bytes=int(cap.get("min_memory_bytes") or 0),
                )
            if slot is None:
                from worker.capacity import ModelSlot  # noqa: PLC0415 — avoids a cycle

                worker.capacity.slots[key] = ModelSlot(
                    engine=cap.get("engine", ""),
                    model_id=cap.get("model_id", ""),
                    derived_concurrency=max(0, declared),
                )
            else:
                slot.derived_concurrency = max(0, declared)

    def stale_workers(self, *, now: Optional[float] = None) -> list[ConnectedWorker]:
        return [w for w in self if w.stale(now=now)]

    def snapshot(self, *, now: Optional[float] = None) -> list[dict]:
        return [w.to_dict(now=now) for w in self]


__all__ = ["ConnectedWorker", "WorkerPool"]
