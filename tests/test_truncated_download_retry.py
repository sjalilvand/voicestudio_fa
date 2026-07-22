"""#1224: a truncated model download aborted the install instead of retrying.

The reporter's log tail, captured just before the backend was SIGKILLed:

    httpx.RemoteProtocolError: peer closed connection without sending complete
    message body (received 4084175097 bytes, expected 4580080592)

That is a 4.6 GB model dying at 4.0 GB — the single most retry-worthy failure
in the whole download path, and it was retried nowhere:

* the installer's retry loop caught ``(HfHubHTTPError, LocalEntryNotFoundError,
  OSError)``. ``httpx.RemoteProtocolError`` inherits ``Exception``, NOT
  ``OSError``, so it escaped all five attempts;
* ``is_hf_connectivity_error`` — the single source of truth for "transient
  download failure" — had no truncation signature, so even a widened catch
  would have classified it as permanent;
* the engine load path (``VoxCPM.from_pretrained``) had no retry at all.

The HF cache is resumable (correctly-sized blobs are skipped by hash), so a
retry continues rather than restarting — which is what makes retrying correct
here and not merely hopeful.
"""
from __future__ import annotations

import pytest

from core.failure import is_hf_connectivity_error
from services import tts_backend


# ── classification ───────────────────────────────────────────────────────


def test_the_reporters_error_is_recognised_as_transient():
    assert is_hf_connectivity_error(
        "peer closed connection without sending complete message body "
        "(received 4084175097 bytes, expected 4580080592)"
    )


@pytest.mark.parametrize(
    "reason",
    [
        # urllib3 / http.client wording for the same truncation.
        "IncompleteRead(4084175097 bytes read, 495905495 more expected)",
        "ProtocolError('Connection broken: IncompleteRead(…)')",
        "http.client.IncompleteRead: incomplete read",
        "Response ended prematurely",
    ],
)
def test_other_truncation_wordings_are_recognised(reason):
    assert is_hf_connectivity_error(reason)


def test_a_real_failure_is_still_permanent():
    """Widening the net must not make genuine errors retry forever."""
    assert not is_hf_connectivity_error("401 Unauthorized: invalid token")
    assert not is_hf_connectivity_error("No such file or directory: config.json")
    assert not is_hf_connectivity_error("CUDA out of memory")


# ── the engine load path retries ─────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_MODEL_LOAD_BACKOFF_S", "0")


def test_truncated_download_is_retried_and_succeeds(monkeypatch):
    calls = []

    def loader():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError(
                "peer closed connection without sending complete message body"
            )
        return "model"

    assert tts_backend._retry_once_with_fresh_hf_client(loader, "VoxCPM2") == "model"
    assert len(calls) == 3


def test_retries_are_bounded(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_MODEL_LOAD_RETRIES", "2")
    calls = []

    def loader():
        calls.append(1)
        raise RuntimeError("peer closed connection without sending complete message body")

    with pytest.raises(RuntimeError):
        tts_backend._retry_once_with_fresh_hf_client(loader, "VoxCPM2")
    assert len(calls) == 2


def test_a_non_transient_failure_is_not_retried():
    calls = []

    def loader():
        calls.append(1)
        raise ValueError("checkpoint has no config.json")

    with pytest.raises(ValueError):
        tts_backend._retry_once_with_fresh_hf_client(loader, "VoxCPM2")
    assert len(calls) == 1, "a permanent failure must fail fast, not retry"


def test_the_closed_client_path_still_resets_the_session(monkeypatch):
    """#880's behaviour must survive the widening."""
    reset = []
    import huggingface_hub.utils as hub_utils

    monkeypatch.setattr(hub_utils, "close_session", lambda: reset.append(1), raising=False)

    calls = []

    def loader():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Cannot send a request, as the client has been closed.")
        return "model"

    assert tts_backend._retry_once_with_fresh_hf_client(loader, "VoxCPM2") == "model"
    assert reset, "the HF session must be reset before retrying a closed client"


def test_the_closed_client_path_stays_single_shot(monkeypatch):
    """The two failure shapes get deliberately different budgets. A closed
    client is a client-state bug, not a network condition: if a FRESH session
    hits it again, repeating won't help, and #880 chose to surface it. Only
    the transient-download path gets the multi-attempt budget."""
    monkeypatch.setenv("OMNIVOICE_MODEL_LOAD_RETRIES", "5")
    calls = []

    def loader():
        calls.append(1)
        raise RuntimeError("Cannot send a request, as the client has been closed.")

    with pytest.raises(RuntimeError):
        tts_backend._retry_once_with_fresh_hf_client(loader, "VoxCPM2")
    assert len(calls) == 2, "closed-client must stay single-shot regardless of the budget"


def test_voxcpm2_load_goes_through_the_retry_wrapper():
    """The #1224 call site itself — a direct from_pretrained here would mean
    the fix above never runs for the engine the reporter was using."""
    import inspect

    src = inspect.getsource(tts_backend.VoxCPM2Backend._ensure_loaded)
    assert "_retry_once_with_fresh_hf_client" in src
    assert "VoxCPM.from_pretrained(checkpoint" not in src.replace(
        "lambda: VoxCPM.from_pretrained(checkpoint", ""
    )


# ── the installer's retry loop catches it ────────────────────────────────


def test_installer_retry_catches_non_oserror_transport_failures():
    """RemoteProtocolError is not an OSError — the loop must decide by
    classification, not by exception type."""
    import inspect

    from api.routers.setup import download

    src = inspect.getsource(download)
    assert "is_hf_connectivity_error" in src, (
        "the install retry loop must classify failures, not match OSError only"
    )


# ── the streaming path leaves an OOM breadcrumb ──────────────────────────


def test_stream_path_checks_memory_before_loading():
    """The reporter was SIGKILLed on a 16 GB Mac. /generate has logged a
    low-memory advisory since the earlier reports of that class, but the
    STREAMING path — which the desktop UI tries first — did not, so the load
    most likely to tip the machine over was the one with no trail in the
    captured stderr tail."""
    import inspect

    from api.routers import tts_stream

    src = inspect.getsource(tts_stream)
    assert "log_if_low" in src
