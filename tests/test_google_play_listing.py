"""The Google Play listing stays within Play's limits and matches the Android app."""

import json
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LISTING = json.loads((ROOT / "store/google-play/listing.json").read_text())


def test_text_fits_play_limits():
    text = LISTING["listing"]
    assert 0 < len(text["title"]) <= 30
    assert 0 < len(text["shortDescription"]) <= 80
    assert 0 < len("\n".join(text["fullDescription"])) <= 4000


def test_package_name_matches_the_app():
    gradle = (ROOT / "mobile/android/app/build.gradle.kts").read_text()
    assert f'applicationId = "{LISTING["packageName"]}"' in gradle


def test_every_manifest_permission_is_declared():
    # A new permission needs its Play Console reason written before it ships.
    manifest = (ROOT / "mobile/android/app/src/main/AndroidManifest.xml").read_text()
    used = set(re.findall(r'uses-permission android:name="([^"]+)"', manifest))
    assert used == set(LISTING["permissions"])


def test_graphics_meet_play_specs():
    icon = Image.open(ROOT / LISTING["graphics"]["icon"])
    assert icon.format == "PNG" and icon.size == (512, 512)
    feature = Image.open(ROOT / LISTING["graphics"]["featureGraphic"])
    # Play rejects a feature graphic with transparency.
    assert feature.format == "PNG" and feature.size == (1024, 500) and feature.mode == "RGB"
    for path in (LISTING["graphics"]["icon"], LISTING["graphics"]["featureGraphic"]):
        assert (ROOT / path).stat().st_size <= 1024 * 1024


def test_store_languages_match_the_phone_models():
    # The listing names the languages phone cloning supports; keep them in step.
    models = json.loads((ROOT / "mobile/contract/models.json").read_text())["models"]
    clone = next(m for m in models if m["capability"] == "clone")
    description = "\n".join(LISTING["listing"]["fullDescription"])
    assert f"cover {len(clone['languages'])} languages" in description
