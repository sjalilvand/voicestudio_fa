"""Read saved Voice Design recipes without weakening OmniVoice's tag validation.

The profile's legacy `instruct` always holds sanitized OmniVoice tags. A
versioned recipe (when present) is the source of the complete natural-language
description for free-form engines; older profiles have no recipe and continue
using their tags.
"""
from __future__ import annotations

import json

from omnivoice.utils.voice_design import heal_design_instruct, instruct_from_vd_states


def _field(row, name: str, default=None):
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return default


def read_recipe(row) -> dict | None:
    raw = _field(row, "design_recipe")
    if not raw:
        return None
    try:
        recipe = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(recipe, dict):
        return None
    if not isinstance(recipe.get("description"), str):
        return None
    if not isinstance(recipe.get("picks"), dict):
        return None
    return recipe


def recipe_engine(row) -> str:
    recipe = read_recipe(row)
    engine = recipe.get("engine") if recipe else None
    return engine if isinstance(engine, str) and engine else "omnivoice"


def profile_instruct(row, engine_id: str | None = None) -> str:
    """Return a design instruction suited to the engine receiving the request.

    OmniVoice always receives validated taxonomy tags, even if a profile was
    originally designed using free-form text on a different model. Free-form
    engines receive the complete description and explicit tags from the
    saved recipe. A legacy row stays unchanged.
    """
    tags = heal_design_instruct(
        _field(row, "instruct"), _field(row, "vd_states")
    )
    recipe = read_recipe(row)
    if _field(row, "kind") != "design" or recipe is None or not engine_id:
        return tags
    from services.tts_backend import get_backend_class

    cls = get_backend_class(engine_id)
    if getattr(cls, "instruct_vocabulary", "tags") != "freeform":
        return tags

    desc = recipe["description"].strip()
    picked = recipe["picks"]
    extras = instruct_from_vd_states(picked)
    return ", ".join(x for x in (desc, extras) if x)
