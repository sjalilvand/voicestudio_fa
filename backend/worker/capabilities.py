"""Capability discovery on a worker.

What the scheduler needs is not "which engines exist" but four separate facts
per model, because they have wildly different consequences:

  * **supported**  — this engine could run on this host at all
  * **installed**  — its sidecar venv is actually present
  * **downloaded** — its weights are on disk (otherwise the first task pays a
                     download, which can be twenty minutes)
  * **resident**   — it is loaded in VRAM right now, which is the difference
                     between eight seconds and several minutes

Collapsing those into one boolean is how a scheduler sends a task to a worker
that then spends a quarter of an hour fetching a model, blows its deadline, and
gets penalised for it.

Everything here is derived from what the app already knows —
``tts_backend.list_backends()`` and ``device_caps`` — rather than a second,
divergent notion of what a worker can do.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("omnivoice.worker")

# gpu_compat families that mean "this would run on the CPU here", which is
# supported but emphatically not accelerated.
_CPU_ONLY = {"cpu"}


def _free_memory_bytes(caps) -> int:
    vram_gb = float(getattr(caps, "vram_gb", 0) or 0)
    return int(vram_gb * 1024**3)


def discover(*, include_unavailable: bool = False) -> list[dict]:
    """Enumerate this host's TTS capabilities in protocol shape.

    Never raises: a worker that cannot introspect one engine must still report
    the others, exactly as ``list_backends`` guarantees locally.
    """
    try:
        from core.device_caps import detect_host_caps  # noqa: PLC0415
        from services import tts_backend  # noqa: PLC0415
    except Exception:
        logger.exception("Capability discovery failed to import the engine layer")
        return []

    try:
        caps = detect_host_caps()
    except Exception:
        logger.exception("Host capability probe failed")
        caps = None

    try:
        backends = tts_backend.list_backends()
    except Exception:
        logger.exception("Engine enumeration failed")
        return []

    free_bytes = _free_memory_bytes(caps) if caps is not None else 0
    family = getattr(caps, "family", "") if caps is not None else ""
    resident = _resident_engine_ids()

    discovered: list[dict] = []
    for entry in backends:
        available = bool(entry.get("available"))
        if not available and not include_unavailable:
            continue
        engine_id = entry.get("id") or ""
        routing = entry.get("routing_status") or ""
        gpu_compat = set(entry.get("gpu_compat") or [])
        discovered.append(
            {
                "engine": engine_id,
                "model_id": model_id_for(entry),
                # The human label, kept OUT of model_id. Free to change with
                # any UI copy edit; nothing keys off it.
                "display_name": entry.get("display_name") or engine_id,
                "operations": _operations_for(entry),
                "supported": available,
                # A subprocess engine is only usable once its venv exists, and
                # `available` already reflects that probe.
                "installed": available,
                # `available` implies the engine can start; weights are fetched
                # on first use, which the load-phase deadline covers.
                "downloaded": available,
                "resident": engine_id in resident,
                "min_memory_bytes": int(float(entry.get("min_vram_gb") or 0) * 1024**3),
                "precision": "",
                "backend": entry.get("effective_device") or family,
                "free_memory_bytes": free_bytes,
                # Capability is not acceleration: an engine present but routed
                # to the CPU here should not be preferred for GPU work.
                "cpu_fallback": routing in ("cpu_fallback", "cpu_only")
                or (gpu_compat and gpu_compat <= _CPU_ONLY),
            }
        )
    return discovered


def model_id_for(entry: dict) -> str:
    """The stable, opaque, engine-scoped identifier for a backend's model.

    ``<engine_id>:<model_key>`` — ``indextts:default``, ``mlx-audio:kokoro``.

    Three things it deliberately is not:

      * **Not a display name.** It was one, and it keys circuit breakers,
        per-model slots and residency (``capacity.py``) and is persisted in
        ``capabilities_json`` and on the task row. A UI copy edit renaming
        "IndexTTS 2" would have orphaned that history.
      * **Not a HuggingFace repo id or any path.** The wire carries ``engine``
        plus this closed identifier and never a repo path, so the worker
        resolves weights from its own catalog and there is nothing to validate
        on arrival.
      * **Not engine-global.** The engine prefix keeps it unique fleet-wide,
        so a breaker or slot keyed on ``model_id`` alone cannot collide across
        two engines that both call their model "base".

    ``default`` covers the one-model-per-engine case. mlx-audio multiplexes
    curated models behind one id (#981) and ``list_backends`` already reports
    which one is configured, so its key rides here — a different curated model
    genuinely is a different model to schedule and to keep resident.
    """
    engine_id = entry.get("id") or ""
    model_key = entry.get("active_model_id") or "default"
    return f"{engine_id}:{model_key}"


def _operations_for(entry: dict) -> list[str]:
    """Which task kinds this engine can serve.

    Cloning is the one genuine split — an engine that cannot clone must never
    be handed a clone task, and ``supports_cloning`` is ``None`` when the
    answer depends on the loaded model, which we treat as "no" rather than
    risk a task that fails at the last moment.
    """
    operations = ["tts"]
    if entry.get("supports_cloning") is True:
        operations.append("clone")
    return operations


def _resident_engine_ids() -> set[str]:
    """Which engines are loaded right now.

    Best effort by design: residency changes underneath us (idle unloading is
    normal), so this is a hint for scheduling, never a guarantee. The worker's
    own accept/reject remains authoritative.
    """
    try:
        from services import model_manager  # noqa: PLC0415
    except Exception:
        return set()
    for attribute in ("resident_engine_ids", "loaded_engine_ids"):
        probe = getattr(model_manager, attribute, None)
        if callable(probe):
            try:
                return set(probe() or ())
            except Exception:
                logger.debug("Residency probe %s failed", attribute, exc_info=True)
    # Fall back to the module's cached active engine, if it exposes one.
    active = getattr(model_manager, "_ACTIVE_TTS_ID", None)
    return {active} if isinstance(active, str) and active else set()


def describe_gpus() -> list[dict]:
    """This host's accelerators, for the worker list in the UI."""
    try:
        from core.device_caps import detect_host_caps  # noqa: PLC0415

        caps = detect_host_caps()
    except Exception:
        return []
    if caps is None:
        return []
    family = getattr(caps, "family", "") or ""
    return [
        {
            "vendor": _vendor_for(family),
            "model": getattr(caps, "device_name", "") or "",
            "backend": family,
            "memory_bytes": _free_memory_bytes(caps),
            "free_memory_bytes": _free_memory_bytes(caps),
            "driver_version": getattr(caps, "driver", "") or "",
        }
    ]


def _vendor_for(family: str) -> str:
    return {
        "cuda": "nvidia",
        "rocm": "amd",
        "mps": "apple",
        "mlx": "apple",
        "xpu": "intel",
    }.get(family, "")


def max_concurrent_tasks(capabilities: Optional[list[dict]] = None) -> int:
    """How many tasks this worker will accept at once.

    Defaults to one, matching the local GPU queue's deliberate single lane —
    the serialisation that exists because concurrent jobs OOM'd VRAM and hit
    posix_spawn EAGAIN on macOS. A worker may advertise more only when every
    capability it reports independently derived more.
    """
    caps = capabilities if capabilities is not None else discover()
    if not caps:
        return 1
    derived = [int(c.get("derived_concurrency") or 0) for c in caps]
    positive = [d for d in derived if d > 0]
    return min(positive) if positive else 1


__all__ = ["describe_gpus", "discover", "max_concurrent_tasks", "model_id_for"]
