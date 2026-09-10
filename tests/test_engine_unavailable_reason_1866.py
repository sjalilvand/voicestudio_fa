"""#1866 — an unavailable engine must say what KIND of problem it has.

Model Catalogue rendered "Engine unavailable. Check installation and
configuration." plus "Last error: A previous engine check failed." for engines
the user had simply never installed. Neither names a missing package, a missing
step, or a next action, and the second reads like a crash or a poisoned cache
rather than "you have not installed this yet".

The probe's own sentence still cannot cross the boundary — it carries exception
text, local paths and sometimes credentials. What changed is that the private
diagnostic is now CLASSIFIED into a VoiceStudio-owned category, the same shape
`_public_routing_reason` already uses for routing.
"""
import pytest

from api.public_engine_metadata import public_backends

_PRIVATE_PATH = "/Users/alice/Library/Caches/secret-token-abc123"


def _reason(diagnostic):
    return public_backends([{"id": "e", "reason": diagnostic}])[0]["reason"]


@pytest.mark.parametrize(
    "diagnostic",
    [
        "voxcpm package not installed.",
        "transformers not installed",
        "funasr not installed. Install with: uv pip install funasr",
        "kittentts not installed: No module named 'kittentts'",
        "omnivoice package missing: cannot import name",
        "mlx-whisper unavailable: not supported on this platform",
    ],
)
def test_a_missing_package_says_so(diagnostic):
    assert "isn't installed yet" in _reason(diagnostic)


@pytest.mark.parametrize(
    "diagnostic",
    [
        "Set ELEVENLABS_API_KEY environment variable.",
        "Configure a server endpoint in Model Catalogue",
        "unconfigured",
    ],
)
def test_a_configuration_gap_says_so(diagnostic):
    assert "needs to be configured" in _reason(diagnostic)


@pytest.mark.parametrize(
    "diagnostic",
    [
        "file is empty (0 bytes) — a placeholder, not a real binary",
        "file is missing",
        "ASR sidecar script missing at /opt/thing/run.py",
    ],
)
def test_a_missing_file_says_so(diagnostic):
    assert "missing or unreadable" in _reason(diagnostic)


def test_an_unrecognised_probe_falls_back_to_the_generic_line():
    # The categories must not guess. Anything unclassified keeps the old text
    # rather than asserting a cause the probe never gave.
    assert _reason("something entirely unexpected") == (
        "Engine unavailable. Check installation and configuration."
    )


@pytest.mark.parametrize(
    "diagnostic",
    [
        f"kittentts not installed: No module named 'kittentts' at {_PRIVATE_PATH}",
        f"file is unreadable ({_PRIVATE_PATH})",
        f"Set ELEVENLABS_API_KEY; current value read from {_PRIVATE_PATH}",
    ],
)
def test_no_private_text_crosses_the_boundary(diagnostic):
    # The whole reason the reason was replaced in the first place.
    out = _reason(diagnostic)
    assert _PRIVATE_PATH not in out
    assert "alice" not in out
    assert "secret-token-abc123" not in out


def test_registry_authored_fields_still_pass_through():
    row = public_backends(
        [
            {
                "id": "e",
                "reason": "voxcpm package not installed.",
                "install_hint": "uv pip install voxcpm",
                "docs_url": "https://example.invalid/docs",
                "setup_snippet": "export FOO=1",
            }
        ]
    )[0]
    assert row["install_hint"] == "uv pip install voxcpm"
    assert row["docs_url"] == "https://example.invalid/docs"
    assert row["setup_snippet"] == "export FOO=1"


def test_the_input_row_is_not_mutated():
    original = {"id": "e", "reason": "voxcpm package not installed."}
    public_backends([original])
    assert original["reason"] == "voxcpm package not installed."
