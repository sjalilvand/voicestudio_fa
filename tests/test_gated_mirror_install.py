"""Gated catalogue installs and Hugging Face mirrors.

The token only ever goes to Hugging Face, so a mirror cannot serve a gated
repository. An automatically picked mirror must therefore never be used for
one, and a mirror the user chose must fail with its own recovery topic instead
of the misleading "set HF_TOKEN / accept the terms" guidance.
"""
import os

os.environ.setdefault("OMNIVOICE_MODEL", "test")
os.environ.setdefault("OMNIVOICE_DISABLE_FILE_LOG", "1")

import pytest

# CLEAN-ROOM (spec W5-small §8): gated-install fixtures and the two install-flow tests.
MIRROR = "https://hf-mirror.com"
CANONICAL = "https://huggingface.co"


@pytest.fixture
def auto_mirror(monkeypatch):
    """Auto mode whose cached decision picked the community mirror."""
    from services import endpoint_race

    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.setattr(endpoint_race, "explicit_endpoint", lambda: "")
    monkeypatch.setattr(endpoint_race, "mode", lambda: "auto")
    monkeypatch.setattr(
        endpoint_race, "cached_decision", lambda: {"endpoint": MIRROR, "reachable": True}
    )
    return endpoint_race


@pytest.fixture
def chosen_mirror(monkeypatch):
    from services import endpoint_race

    monkeypatch.setenv("HF_ENDPOINT", MIRROR)
    return endpoint_race


def test_auto_picked_mirror_serves_only_public_repositories(auto_mirror):
    assert auto_mirror.download_endpoint() == MIRROR
    assert auto_mirror.download_endpoint(gated=True) == CANONICAL


def test_chosen_mirror_is_kept_for_gated_repositories(chosen_mirror):
    assert chosen_mirror.download_endpoint(gated=True) == MIRROR
    assert chosen_mirror.explicit_mirror() == MIRROR


def test_chosen_official_endpoint_is_not_a_mirror(monkeypatch):
    from services import endpoint_race

    monkeypatch.setenv("HF_ENDPOINT", CANONICAL)
    assert endpoint_race.explicit_mirror() == ""
    assert endpoint_race.download_endpoint(gated=True) == CANONICAL


def test_mirror_gated_topic_is_registered():
    from core.failure import public_hint_for_topic

    assert "Hugging Face (official)" in public_hint_for_topic("HF_MIRROR_GATED")
