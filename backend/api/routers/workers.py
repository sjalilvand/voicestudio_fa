"""Remote worker management API.

Deliberately small. The council's warning about the original design was that
seven strategies times three execution modes times priorities times weights
times per-model concurrency is a configuration surface nobody can test and
every knob is a compatibility promise forever. So this exposes what a user
actually needs to run their other GPU: see workers, add one, name it, prefer
one, pause one, remove one.

Two things here are not conveniences and must not be softened:

  * **Consent is explicit and per worker.** Audio, reference voices, and text
    leave the machine for a worker, so each one is approved individually. There
    is no global "trust all workers".
  * **A token is shown exactly once.** Only its hash is stored, so it cannot be
    re-displayed — which is the point.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import require_loopback
from worker import registry, routing, service

logger = logging.getLogger("omnivoice.worker")

# Management is loopback-only: these endpoints mint join tokens and revoke
# machines, so they follow the same rule as the app's other privileged routes.
router = APIRouter(prefix="/workers", tags=["workers"], dependencies=[Depends(require_loopback)])


class EnableRequest(BaseModel):
    enabled: bool


class EnrollRequest(BaseModel):
    label: str = Field("", max_length=120)
    endpoint: str = Field("", max_length=256)
    ttl_seconds: int = Field(900, ge=60, le=24 * 3600)


class TargetRequest(BaseModel):
    """`local`, or the id of an enrolled worker."""

    target: str = Field(..., max_length=64)


class WorkerUpdate(BaseModel):
    name: str | None = Field(None, max_length=120)
    enabled: bool | None = None
    priority: int | None = Field(None, ge=0, le=100)


@router.get("")
def list_workers() -> dict:
    """Everything the workers panel renders, in one call."""
    return service.control_plane.snapshot()


@router.get("/target")
def get_target() -> dict:
    """What the GPU picker shows: the choice, the resolved answer, the options.

    `active` is the same answer the generation path uses, so the badge cannot
    claim work goes somewhere the router will not send it.
    """
    return routing.status()


@router.post("/target")
def set_target(request: TargetRequest) -> dict:
    """Choose where work runs. Exactly one target is active at a time."""
    chosen = request.target.strip() or routing.LOCAL
    if chosen != routing.LOCAL:
        worker = registry.get(chosen)
        if worker is None or worker.revoked:
            raise HTTPException(status_code=404, detail="No such worker.")
    routing.set_target_id(chosen)
    return routing.status()


@router.post("/enabled")
async def set_enabled(request: EnableRequest) -> dict:
    """Turn the feature on or off.

    Off means off: the control plane stops, the listening socket closes, and
    the app is exactly what it was before the toggle existed.
    """
    service.set_remote_workers_enabled(request.enabled)
    if request.enabled:
        await service.control_plane.start()
    else:
        await service.control_plane.stop()
    return service.control_plane.snapshot()


@router.post("/enrollments")
def create_enrollment(request: EnrollRequest) -> dict:
    """Mint a single-use join token.

    The plaintext is returned once and never stored — the response is the only
    time it exists outside the worker that redeems it.
    """
    if not service.control_plane.running:
        raise HTTPException(
            status_code=409,
            detail="Remote workers are turned off. Enable them in Settings → System → Remote workers first.",
        )
    token = service.control_plane.create_enrollment(
        endpoint=request.endpoint, label=request.label, ttl_seconds=request.ttl_seconds
    )
    return {
        "token": token.encode(),
        "endpoint": token.endpoint,
        "fingerprint": token.cert_fingerprint,
        "expires_at": token.expires_at,
        "shown_once": True,
    }


@router.patch("/{worker_id}")
def update_worker(worker_id: str, request: WorkerUpdate) -> dict:
    worker = registry.get(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="No such worker.")
    if request.name is not None:
        registry.rename(worker_id, request.name)
    if request.enabled is not None:
        registry.set_enabled(worker_id, request.enabled)
    if request.priority is not None:
        registry.set_priority(worker_id, request.priority)
    updated = registry.get(worker_id)
    # Keep the live copy in step, so the scheduler and its logs do not go on
    # using the name or priority this worker had when it connected.
    if updated is not None and service.control_plane.running:
        service.control_plane.pool.refresh_record(updated)
    return updated.to_dict() if updated else {}


@router.post("/{worker_id}/consent")
def grant_consent(worker_id: str) -> dict:
    """Record the user's explicit yes to sending their audio to this machine."""
    if registry.get(worker_id) is None:
        raise HTTPException(status_code=404, detail="No such worker.")
    registry.grant_consent(worker_id)
    worker = registry.get(worker_id)
    return worker.to_dict() if worker else {}


@router.post("/{worker_id}/resume")
def clear_breaker(worker_id: str) -> dict:
    """Clear a paused worker's circuit breakers.

    The user fixed the machine and knows it — a breaker with no manual clear is
    the quarantine trap the reputation system had.
    """
    if not service.control_plane.running:
        raise HTTPException(status_code=409, detail="Remote workers are turned off.")
    breakers = service.control_plane.pool.breakers
    for breaker in breakers.open_breakers(worker_id):
        breaker.force_close()
    return {"ok": True}


@router.delete("/{worker_id}")
def revoke_worker(worker_id: str) -> dict:
    """Remove a worker — which means revoke its key, not hide the row.

    Its in-flight work is released so it can be retried elsewhere rather than
    waiting out a lease on a machine that will never answer again.
    """
    if registry.get(worker_id) is None:
        raise HTTPException(status_code=404, detail="No such worker.")
    registry.revoke(worker_id)
    if service.control_plane.running:
        service.control_plane.scheduler.on_disconnected(worker_id)
        service.control_plane.pool.breakers.forget_worker(worker_id)
    return {"ok": True, "revoked": worker_id}


@router.get("/tasks")
def list_tasks(limit: int = 50) -> dict:
    """Recent remote tasks, for the queue view."""
    if not service.control_plane.running:
        return {"tasks": [], "queue_depth": 0}
    from worker import task_store  # noqa: PLC0415

    return {
        "queue_depth": service.control_plane.scheduler.queue_depth,
        "tasks": [t.to_dict() for t in task_store.list_tasks(limit=min(200, max(1, limit)))],
    }


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    if not service.control_plane.running:
        raise HTTPException(status_code=409, detail="Remote workers are turned off.")
    cancelled = service.control_plane.scheduler.cancel(task_id, reason="cancelled by user")
    if not cancelled:
        raise HTTPException(status_code=404, detail="No such active task.")
    return {"ok": True}
