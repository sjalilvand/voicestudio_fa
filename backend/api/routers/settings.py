"""Settings API — HF token save/clear/state endpoints (Phase 1 AUTH-03 backend half).

These endpoints are the backend half of the Wave 2 Settings → API Keys
panel. Threat T-01-03 mitigation: every write endpoint is gated by the
router-level `require_loopback` dep, so non-loopback origins get 403
before the handler runs. Reads are loopback-gated too — the masked
token preview is useful telemetry that we still don't want exposed on
the LAN.

The state endpoint duplicates `/system/hf-token/state` (which lives on
`system.py` for legacy-router compatibility); both return the same shape.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import require_loopback

logger = logging.getLogger("omnivoice.api.settings")

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_loopback)],
)


class _HFTokenBody(BaseModel):
    token: str = Field(..., min_length=1, description="HuggingFace access token")


def _state_response() -> dict:
    """Return the same shape the React panel renders. Never includes raw token."""
    from services import token_resolver

    s = token_resolver.state()
    return {
        "active": s["active"],
        "sources": [asdict(row) for row in s["sources"]],
    }


@router.post("/hf-token")
def save_hf_token(body: _HFTokenBody):
    """Persist a new HF token to the encrypted settings store + the HF
    canonical file (via huggingface_hub.login). Returns the updated
    cascade state."""
    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="token must be non-empty")
    from services import token_resolver
    try:
        token_resolver.save_app_token(token)
    except Exception:
        logger.exception("save_app_token failed")
        raise HTTPException(status_code=500, detail="Failed to save HF token")
    return _state_response()


@router.delete("/hf-token")
def clear_hf_token(also_clear_hf_cli: bool = Query(False)):
    """Clear the App-source token. Optionally also call huggingface_hub.logout
    to clear the canonical HF file. Returns the updated cascade state."""
    from services import token_resolver
    try:
        token_resolver.clear_app_token(also_clear_hf_cli=also_clear_hf_cli)
    except Exception:
        logger.exception("clear_app_token failed")
        raise HTTPException(status_code=500, detail="Failed to clear HF token")
    return _state_response()


@router.get("/hf-token/state")
def get_hf_token_state():
    """3-source HF token cascade state for the Settings UI."""
    return _state_response()
