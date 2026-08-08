"""An HTTP status code in an error message must be a token, not a substring.

`classify()` matched `"401" in low`, so any text carrying those three digits
anywhere was read as an HTTP 401 and classified `HF_AUTH_FAILED` — a class
whose remedy is "Set a valid HF_TOKEN in Settings → Hugging Face and retry."

That remedy cannot help when the digits came from a file path, and it sends
the user to edit credentials to fix something unrelated. Worse, `"401"` sat
on BOTH sides of that branch's conjunction, so the `and` was vacuous for it:
one stray path component was the entire match.

It surfaced in CI rather than from a user report. `test_synth_error_classes.py`
asserts a failed audio write classifies `AUDIO_IO_FAILED`; the enriched message
names the target file, and once the runner's scratch counter reached
`/tmp/pytest-of-runner/pytest-401/` the audio failure classified as an HF auth
failure and the test failed. The same message on the same code passes on a
runner whose counter reads 400 or 402 — the bug was environment-shaped, which
is why nothing caught it for as long as it existed.

The user-facing half is not hypothetical: a cloned voice saved as
`clip401.wav`, a job id, or a bitrate is enough.

Two conditions are needed, not one. Tokenising the digits fixes `clip401.wav`
and `pytest-401` but not `job 401 failed to start`, where 401 genuinely is a
standalone token and still is not a status code — so the message must also
read like an HTTP exchange. Both halves are pinned below, because dropping
either one readmits a different family of false positives.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def failure():
    """Resolve per test — a module-level import can bind a stale sys.modules
    entry when another suite has rebound it."""
    return importlib.import_module("core.failure")


# Text where 401 is a genuine HTTP status and the HF class is correct.
REAL_401 = [
    "401 Client Error: Unauthorized for url: https://huggingface.co/meta/model",
    "HTTP 401 while contacting the licence server",
    "Received 401, check your token",
    "Unauthorized (401) response from the model host",
]

# Text where the digits are not a status code. None of these may claim an HF
# auth failure — each would tell the user to go fix a token for no reason.
NOT_A_401 = [
    "Error opening '/data/voices/clip401.wav': System error.",
    "Error opening '/tmp/pytest-of-runner/pytest-401/test_save0/speech.wav': System error.",
    "bitrate 401000 unsupported",
    "job 401 failed to start",
    "cuda error on device 401",
    "sample rate 44100 vs 401 mismatch",
]


@pytest.mark.parametrize("text", REAL_401)
def test_a_real_http_401_is_still_detected(failure, text):
    assert failure.has_http_401(text.lower()), (
        f"a genuine HTTP 401 stopped being recognised: {text!r}"
    )


@pytest.mark.parametrize("text", NOT_A_401)
def test_digits_inside_other_text_are_not_a_status_code(failure, text):
    assert not failure.has_http_401(text.lower()), (
        f"{text!r} has no HTTP 401 in it, but one was detected"
    )


@pytest.mark.parametrize("text", NOT_A_401)
def test_such_messages_never_classify_as_an_hf_auth_failure(failure, text):
    """The end-to-end statement: the remedy the user is shown."""
    assert failure.classify(text) != "HF_AUTH_FAILED", (
        f"{text!r} was given the 'set an HF token' remedy, which cannot help it"
    )


def test_the_audio_write_failure_that_exposed_this_keeps_its_own_class(failure):
    """The exact CI failure: a scratch path carrying 401 must not steal the
    class from the audio error that actually occurred."""
    innocent = (
        "Error opening '/tmp/pytest-of-runner/pytest-3/t/speech.wav': System error."
    )
    unlucky = (
        "Error opening '/tmp/pytest-of-runner/pytest-401/t/speech.wav': System error."
    )
    assert failure.classify(innocent) == failure.classify(unlucky), (
        "the same failure classified differently depending on which scratch "
        "directory pytest happened to allocate"
    )


def test_a_hyphenated_build_tag_is_not_a_status_code(failure):
    """`\\b401\\b` would still match `pytest-401` — a hyphen is a word boundary.
    Pinning the stricter rule so a future simplification cannot reintroduce
    the exact failure this test exists for."""
    assert not failure.has_http_401("run-401-retry timed out")
    assert not failure.has_http_401("/tmp/pytest-401/x")
