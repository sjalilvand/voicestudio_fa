import importlib.util
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_electron_release import validate_sunset

def feed(url="https://github.com/debpalash/VoiceStudio/releases/download/v1.2.3/app.tar.gz"):
    return {"version": "1.2.3", "platforms": {"linux-x86_64": {"url": url, "signature": "signed"}}}

def test_sunset_feed_stays_on_immutable_tauri_release():
    validate_sunset(feed(), "v1.2.3")

@pytest.mark.parametrize("url", [
    "https://github.com/debpalash/VoiceStudio/releases/latest/download/app.tar.gz",
    "https://example.com/debpalash/VoiceStudio/releases/download/v1.2.3/app.tar.gz",
    "https://github.com/debpalash/VoiceStudio/releases/download/v2.0.0/app.exe",
])
def test_sunset_rejects_redirecting_legacy_clients(url):
    with pytest.raises(ValueError):
        validate_sunset(feed(url), "v1.2.3")

def test_sunset_requires_signed_payload_and_matching_version():
    data = feed()
    data["platforms"]["linux-x86_64"]["signature"] = ""
    with pytest.raises(ValueError):
        validate_sunset(data, "v1.2.3")
    with pytest.raises(ValueError):
        validate_sunset(feed(), "v1.2.4")
