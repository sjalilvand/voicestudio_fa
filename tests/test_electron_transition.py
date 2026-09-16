import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
@pytest.fixture
def validate_sunset(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("release_helper_test", ROOT / "scripts/prepare_electron_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_sunset

def feed(url="https://github.com/debpalash/VoiceStudio/releases/download/v1.2.3/app.tar.gz"):
    return {"version": "1.2.3", "platforms": {"linux-x86_64": {"url": url, "signature": "signed"}}}

def test_sunset_feed_stays_on_immutable_tauri_release(validate_sunset):
    validate_sunset(feed(), "v1.2.3")

@pytest.mark.parametrize("url", [
    "https://github.com/debpalash/VoiceStudio/releases/latest/download/app.tar.gz",
    "https://example.com/debpalash/VoiceStudio/releases/download/v1.2.3/app.tar.gz",
    "https://github.com/debpalash/VoiceStudio/releases/download/v2.0.0/app.exe",
])
def test_sunset_rejects_redirecting_legacy_clients(url, validate_sunset):
    with pytest.raises(ValueError):
        validate_sunset(feed(url), "v1.2.3")

def test_sunset_requires_signed_payload_and_matching_version(validate_sunset):
    data = feed()
    data["platforms"]["linux-x86_64"]["signature"] = ""
    with pytest.raises(ValueError):
        validate_sunset(data, "v1.2.3")
    with pytest.raises(ValueError):
        validate_sunset(feed(), "v1.2.4")


def test_electron_release_scopes_signing_secrets_and_gates_unsigned_owner_dispatch():
    import yaml
    workflow = yaml.load((ROOT / ".github/workflows/electron-release.yml").read_text(), Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]
    assert "CSC_LINK" not in jobs["package"]["env"]
    assert "CSC_KEY_PASSWORD" not in jobs["package"]["env"]
    scoped = [step for step in jobs["package"]["steps"] if "CSC_LINK" in step.get("env", {})]
    assert [step["name"] for step in scoped] == ["Package without publishing"]
    guard = next(step for step in jobs["validate"]["steps"] if step.get("name") == "Require an exact version tag")
    assert 'test "$DISPATCH_ACTOR" = "$OWNER" && test "$RERUN_ACTOR" = "$OWNER"' in guard["run"]
    assert guard["env"]["DISPATCH_ACTOR"] == "${{ github.actor }}"
    assert guard["env"]["RERUN_ACTOR"] == "${{ github.triggering_actor }}"
    publish = jobs["release"]["steps"][-1]
    assert publish["if"] == "github.event_name == 'workflow_dispatch' && inputs.publish == true"
