"""Per-model licence acceptance: a non-commercial-category model is unusable until accepted.

VoiceStudio is not the licensor of any model and cannot grant model access.
Acceptance records that the user confirmed they have the rights the model's
own licence requires (for example non-commercial use, or a separate grant
from the rights holder). It is a local, honest-acknowledgement gate, not a
security boundary and not legal clearance.

Every model whose declared licence category is not ``commercial`` (see
``model_licenses.license_category``) needs acceptance. Acceptance is bound to
a fingerprint of the recorded terms, so changed terms ask again. Unknown and
unmapped licences fail closed: they are gated.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Iterable

from services import model_licenses

logger = logging.getLogger(__name__)

ERROR_CODE = "model_licence_required"
_KEY_PREFIX = "model_licence_accepted:"
# Pre-existing per-engine acceptances that covered the same upstream terms.
# They count once, so users who already accepted are not asked twice.
_LEGACY_ENGINE_ACCEPTANCE = {"supertone/supertonic-3": "supertonic3"}

_cache_lock = threading.Lock()
_cache: tuple[float, dict] | None = None


class ModelLicenceNotAccepted(RuntimeError):
    """Raised before a gated model is loaded or used without acceptance."""

    def __init__(self, models: list[dict]):
        self.models = models
        names = ", ".join(m["repo_id"] for m in models)
        super().__init__(
            f"Licence not accepted for {names}. Review and accept it in Model Manager."
        )

    def detail(self) -> dict:
        return {"code": ERROR_CODE, "message": str(self), "models": self.models}


def _registry() -> dict:
    """Registry cached by file mtime; it changes only on app update."""
    global _cache
    path = model_licenses.REGISTRY_PATH
    mtime = Path(path).stat().st_mtime
    with _cache_lock:
        if _cache is None or _cache[0] != mtime:
            _cache = (mtime, model_licenses.load_registry(path))
        return _cache[1]


def _disclosure(repo_id: str) -> dict:
    try:
        return model_licenses.disclosure(repo_id, _registry())
    except Exception:  # noqa: BLE001 — a malformed registry must fail closed
        logger.warning("model licence registry unreadable", exc_info=True)
        return {"license_category": "unknown", "license": None, "blockers": ["registry_invalid"]}


def fingerprint(info: dict) -> str:
    """Digest of the terms a user accepts; changes when the recorded terms change."""
    terms = {
        "license": info.get("license"),
        "license_category": info.get("license_category"),
        "commercial_inference": info.get("commercial_inference"),
        "commercial_outputs": info.get("commercial_outputs"),
        "variants": sorted(
            [v.get("id"), v.get("license_category"), v.get("commercial_inference")]
            for v in info.get("variants") or []
        ),
    }
    blob = json.dumps(terms, sort_keys=True, separators=(",", ":"))
    return "v1:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _key(repo_id: str) -> str:
    return _KEY_PREFIX + repo_id.casefold()


def _stored(repo_id: str) -> str | None:
    from services import settings_store

    try:
        return settings_store.get_text(_key(repo_id))
    except Exception:  # noqa: BLE001 — unreadable settings fail closed
        logger.warning("model licence acceptance unreadable", exc_info=True)
        return None


def _legacy_accepted(repo_id: str) -> bool:
    engine = _LEGACY_ENGINE_ACCEPTANCE.get(repo_id.casefold())
    if engine is None:
        return False
    from services import settings_store

    try:
        return settings_store.get_license_accepted(engine)
    except Exception:  # noqa: BLE001
        return False


def status(repo_id: str) -> dict:
    """``{repo_id, category, required, accepted, fingerprint}`` for one model."""
    info = _disclosure(repo_id)
    category = info.get("license_category") or "unknown"
    required = category != "commercial"
    current = fingerprint(info)
    accepted = not required or _stored(repo_id) == current or (
        _stored(repo_id) is None and _legacy_accepted(repo_id)
    )
    return {
        "repo_id": repo_id,
        "license": info.get("license"),
        "category": category,
        "required": required,
        "accepted": accepted,
        "fingerprint": current,
    }


def accept(repo_id: str, expected_fingerprint: str) -> dict:
    """Record acceptance of exactly the terms the user was shown."""
    current = status(repo_id)
    if expected_fingerprint != current["fingerprint"]:
        raise ValueError("terms_changed")
    from services import settings_store

    settings_store.set_text(_key(repo_id), current["fingerprint"])
    return status(repo_id)


def revoke(repo_id: str) -> dict:
    from services import settings_store

    # An explicit non-fingerprint value also overrides any legacy acceptance.
    settings_store.set_text(_key(repo_id), "revoked")
    return status(repo_id)


def ensure_accepted(repo_ids: Iterable[str]) -> None:
    """Raise ``ModelLicenceNotAccepted`` listing every unaccepted gated model."""
    missing = []
    for repo_id in dict.fromkeys(r for r in repo_ids if r):
        state = status(repo_id)
        if state["required"] and not state["accepted"]:
            missing.append({k: state[k] for k in ("repo_id", "license", "category", "fingerprint")})
    if missing:
        raise ModelLicenceNotAccepted(missing)


def repos_for_engine(engine_id: str, identity: str | None = None) -> list[str]:
    """Registry models an engine loads.

    ``identity`` is the concrete model a preference-dependent engine will load
    (for example mlx-audio's selected repo). Without one, every registry model
    recorded for the engine applies: the engine ships them all.
    """
    try:
        rows = _registry()["models"]
    except Exception:  # noqa: BLE001
        rows = []
    if identity and "/" in identity:
        return [identity]
    return [row["id"] for row in rows if engine_id in (row.get("engines") or [])]


def ensure_engine_accepted(engine_id: str, identity: str | None = None) -> None:
    ensure_accepted(repos_for_engine(engine_id, identity))
