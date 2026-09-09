"""FDL-09: the segmented (multi-connection) downloader is ON by default.

The app forces the legacy-LFS path (HF_HUB_DISABLE_XET=1) for clear progress,
which is single-stream and slow. The segmented accelerator restores parallel
byte-range speed with a safe fallback to snapshot_download — so it ships ON by
default for fast first-run downloads. This pins the default so it can't silently
regress to opt-in, and that the env override still disables it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from api.routers.setup.download import _segmented_enabled  # noqa: E402


def test_segmented_is_on_by_default(monkeypatch):
    monkeypatch.delenv("OMNIVOICE_SEGMENTED_DOWNLOAD", raising=False)
    assert _segmented_enabled() is True


def test_env_override_can_disable(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_SEGMENTED_DOWNLOAD", "0")
    assert _segmented_enabled() is False


def test_env_override_truthy_keeps_it_on(monkeypatch):
    for val in ("1", "true", "on", "yes"):
        monkeypatch.setenv("OMNIVOICE_SEGMENTED_DOWNLOAD", val)
        assert _segmented_enabled() is True


# The accelerator must be re-entered on the NEXT attempt after a dropped
# connection, so it resumes from its .part manifest. Falling straight through to
# snapshot_download in the same attempt finishes the install from a separate
# .incomplete file and strands the manifest — restart-from-zero all over again.

import httpx  # noqa: E402

from api.routers.setup.download import _segmented_retry_plan  # noqa: E402

_MAX = 5


def _dropped():
    return httpx.RemoteProtocolError(
        "peer closed connection without sending complete message body"
    )


def test_dropped_connection_reraises_so_the_next_attempt_resumes():
    for attempt in (1, 2, 3):
        disable, reraise = _segmented_retry_plan(_dropped(), attempt, _MAX)
        assert reraise is True, f"attempt {attempt} must reach the outer retry"
        assert disable is False, f"attempt {attempt} must keep the accelerator"


def test_final_attempt_is_reserved_for_the_plain_path():
    """The accelerator can never be the reason an install fails outright."""
    disable, reraise = _segmented_retry_plan(_dropped(), _MAX - 1, _MAX)
    assert (disable, reraise) == (True, False)
    disable, reraise = _segmented_retry_plan(_dropped(), _MAX, _MAX)
    assert (disable, reraise) == (True, False)


def test_a_non_network_failure_disables_the_accelerator_at_once():
    """An accelerator that cannot work here must not burn every retry."""
    disable, reraise = _segmented_retry_plan(ValueError("sha256 mismatch"), 1, _MAX)
    assert (disable, reraise) == (True, False)
