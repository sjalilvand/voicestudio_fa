"""#2040 — the MCP tools gave up after a fixed 120 s while the backend's own
budgets run longer (ASR: 300 s), so a transcription the backend would have
finished came back as an empty client-side timeout."""
import pytest

_BUDGET_VARS = (
    "OMNIVOICE_MCP_TIMEOUT_S",
    "OMNIVOICE_ASR_TRANSCRIBE_TIMEOUT_S",
    "OMNIVOICE_GENERATE_TIMEOUT_S",
    "OMNIVOICE_CPU_GENERATE_TIMEOUT_S",
)


@pytest.fixture
def post_timeout(monkeypatch):
    for name in _BUDGET_VARS:
        monkeypatch.setenv(name, "1")  # recorded, so the teardown restores it
        monkeypatch.delenv(name)
    import mcp_server

    return mcp_server._post_timeout_s


def test_transcribe_waits_past_the_backends_asr_budget(post_timeout):
    assert post_timeout("transcribe") == 330.0


def test_a_raised_asr_budget_is_followed(post_timeout, monkeypatch):
    monkeypatch.setenv("OMNIVOICE_ASR_TRANSCRIBE_TIMEOUT_S", "900")
    assert post_timeout("transcribe") == 930.0


def test_generation_follows_the_backend_budget_and_text_length(post_timeout, monkeypatch):
    assert post_timeout("generate", "short") == 630.0
    assert post_timeout("generate", "x" * 1600) == 640.0
    monkeypatch.setenv("OMNIVOICE_GENERATE_TIMEOUT_S", "1200")
    assert post_timeout("generate", "short") == 1230.0


def test_an_explicit_mcp_timeout_still_wins(post_timeout, monkeypatch):
    monkeypatch.setenv("OMNIVOICE_MCP_TIMEOUT_S", "45")
    assert post_timeout("transcribe") == 45.0
    assert post_timeout("generate", "x" * 5000) == 45.0


def test_other_posts_keep_the_old_default(post_timeout):
    assert post_timeout() == 120.0


def test_unusable_values_fall_back(post_timeout, monkeypatch):
    monkeypatch.setenv("OMNIVOICE_ASR_TRANSCRIBE_TIMEOUT_S", "soon")
    assert post_timeout("transcribe") == 330.0
    monkeypatch.setenv("OMNIVOICE_MCP_TIMEOUT_S", "-5")
    assert post_timeout("transcribe") == 120.0
