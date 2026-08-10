"""Where work runs: this machine, or one node the user picked.

The scheduler underneath can rank many workers, and the hosted platform will
need that. The OSS product deliberately does not expose it. Here the user
chooses a single target from a list — ``Local``, or one of the machines they
enrolled — and that choice is the whole policy:

    GPU: [ Local ▾ ]        Local
                            desktop-4090    192.168.0.222:2222
                            laptop-m2       192.168.0.31:7443

Two reasons this beats automatic selection for a desktop app. It is
predictable — a user who sends a job to their 4090 can see that is where it
went, rather than discovering the scheduler preferred a laptop. And it is
explainable when it goes wrong: "your chosen worker is offline, this ran
locally" is a sentence; "least-busy ranking picked another node" is not.

Exactly one target is active at a time. Other enrolled workers may be
connected — they simply receive nothing, which is what standby means.

Fallback is deliberate and quiet: if the chosen worker cannot take the job,
the work runs locally rather than failing. A user whose remote GPU went to
sleep should get their audio, not an error about infrastructure.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("omnivoice.worker")

# Sentinel for "run on this machine". Not a worker id, and never confusable
# with one: worker ids are 12 hex characters.
LOCAL = "local"

_SETTING_KEY = "worker_target"


@dataclass(frozen=True)
class Target:
    """One selectable entry in the GPU picker."""

    id: str
    label: str
    endpoint: str = ""
    connected: bool = False
    available: bool = False
    detail: str = ""
    # ready | busy | offline — what the header dot is coloured on.
    status: str = "offline"
    latency_ms: float = 0.0
    active_tasks: int = 0
    max_tasks: int = 0

    @property
    def is_local(self) -> bool:
        return self.id == LOCAL

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "endpoint": self.endpoint,
            "connected": self.connected,
            "available": self.available,
            "detail": self.detail,
            "is_local": self.is_local,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 1),
            "active_tasks": self.active_tasks,
            "max_tasks": self.max_tasks,
        }


def get_target_id() -> str:
    """The user's choice, or Local.

    Persisted, because a target that resets to Local on every app start would
    quietly send work to the wrong machine after a restart.
    """
    try:
        from services import settings_store  # noqa: PLC0415

        stored = (settings_store.get_text(_SETTING_KEY, "") or "").strip()
    except Exception:
        return LOCAL
    return stored or LOCAL


def set_target_id(target_id: str) -> str:
    """Record the user's choice. Returns what was actually stored."""
    from services import settings_store  # noqa: PLC0415

    chosen = (target_id or LOCAL).strip() or LOCAL
    settings_store.set_text(_SETTING_KEY, chosen)
    return chosen


def local_target(*, label: str = "Local") -> Target:
    # This machine is reachable by definition and has no network latency to
    # report — showing "0 ms" next to it would invite a false comparison.
    return Target(id=LOCAL, label=label, connected=True, available=True, status="ready")


def list_targets(control_plane=None) -> list[Target]:
    """Local first, then every enrolled worker.

    Revoked workers are omitted; a disabled or disconnected one is listed but
    not ``available``, so the picker can show it greyed rather than pretending
    the machine vanished.
    """
    targets = [local_target()]
    if control_plane is None:
        from worker.service import control_plane as default_plane  # noqa: PLC0415

        control_plane = default_plane

    try:
        from worker import registry  # noqa: PLC0415

        enrolled = registry.list_workers()
    except Exception:
        logger.debug("Could not list enrolled workers", exc_info=True)
        return targets

    pool = getattr(control_plane, "pool", None) if control_plane.running else None
    for record in enrolled:
        live = pool.get(record.id) if pool is not None else None
        connected = live is not None and not live.stale()
        available, detail = _availability(record, live, pool)
        targets.append(
            Target(
                id=record.id,
                label=record.name or record.key_id,
                # The address it connected FROM beats any self-reported one.
                endpoint=(live.address if live and live.address else record.endpoint),
                connected=connected,
                available=available,
                detail=detail,
                status=_status_for(record, live, available),
                latency_ms=live.latency_ms if live else 0.0,
                active_tasks=live.capacity.active_tasks if live else 0,
                max_tasks=live.capacity.max_concurrent_tasks if live else 0,
            )
        )
    return targets


def _status_for(record, live, available: bool) -> str:
    """ready / busy / offline — the three states the header dot colours on.

    A worker that is connected but unusable for a config reason (disabled, not
    approved, paused) is NOT "ready"; calling it ready would promise work can
    go there when it cannot.
    """
    if live is None or live.stale():
        return "offline"
    if available:
        return live.status
    return "busy" if live.status == "busy" else "offline"


def _availability(record, live, pool) -> tuple[bool, str]:
    """Can this worker take work right now, and if not, why not?

    The reason is user-facing: it is what the picker shows under a greyed
    entry, so it has to name something the user can act on.
    """
    if record.revoked:
        return False, "removed"
    if not record.enabled:
        return False, "disabled"
    if record.consent_granted_at is None:
        return False, "not approved"
    if live is None:
        return False, "offline"
    if live.stale():
        return False, "not responding"
    if live.draining:
        return False, "shutting down"
    if pool is not None and pool.breakers.open_breakers(record.id):
        return False, "paused after repeated failures"
    return True, ""


@dataclass(frozen=True)
class Decision:
    """Where one job should run, and why."""

    remote: bool
    worker_id: Optional[str] = None
    label: str = "Local"
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "remote": self.remote,
            "worker_id": self.worker_id,
            "label": self.label,
            "reason": self.reason,
        }


def decide(control_plane=None) -> Decision:
    """Resolve the user's choice against what is actually reachable.

    This is the single answer to "where does the next job run", used both by
    the generation path and by the header badge — so the badge cannot claim
    something the router will not do.
    """
    target_id = get_target_id()
    if target_id == LOCAL:
        return Decision(remote=False, reason="chosen")

    if control_plane is None:
        from worker.service import control_plane as default_plane  # noqa: PLC0415

        control_plane = default_plane

    if not control_plane.running:
        return Decision(remote=False, reason="remote workers are turned off")

    for target in list_targets(control_plane):
        if target.id != target_id:
            continue
        if target.available:
            return Decision(
                remote=True, worker_id=target.id, label=target.label, reason="chosen"
            )
        # Chosen but unusable: run locally and say which machine was skipped.
        return Decision(
            remote=False,
            label="Local",
            reason=f"{target.label} is {target.detail or 'unavailable'} — running locally",
        )

    # The chosen worker no longer exists (removed on another device, or the
    # row was cleaned up). Fall back rather than stranding the user.
    return Decision(remote=False, reason="the chosen worker no longer exists — running locally")


def status(control_plane=None) -> dict:
    """Everything the GPU picker needs, in one call."""
    decision = decide(control_plane)
    return {
        "target": get_target_id(),
        "active": decision.to_dict(),
        "targets": [t.to_dict() for t in list_targets(control_plane)],
    }


__all__ = [
    "LOCAL",
    "Decision",
    "Target",
    "decide",
    "get_target_id",
    "list_targets",
    "local_target",
    "set_target_id",
    "status",
]
