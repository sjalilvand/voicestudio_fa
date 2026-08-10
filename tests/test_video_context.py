"""Pillow-backed video-context analysis stays deterministic across upgrades."""
from __future__ import annotations

from PIL import Image

from services.video_context import _analyse_frame_basic


def _save_jpeg(tmp_path, name: str, image: Image.Image):
    path = tmp_path / name
    image.save(path, format="JPEG", quality=100, subsampling=0)
    return path


def test_basic_analysis_decodes_and_resizes_real_jpegs(tmp_path):
    dark = _save_jpeg(tmp_path, "dark.jpg", Image.new("RGB", (16, 12), (20, 20, 20)))
    bright = _save_jpeg(tmp_path, "bright.jpg", Image.new("RGB", (640, 480), (230, 230, 230)))

    dark_result = _analyse_frame_basic(str(dark))
    bright_result = _analyse_frame_basic(str(bright))

    assert dark_result == {
        "brightness": "dark", "mood": "calm", "complexity": "simple",
        "avg_luminance": 20.0, "avg_saturation": 0.0,
    }
    assert bright_result == {
        "brightness": "bright", "mood": "calm", "complexity": "simple",
        "avg_luminance": 230.0, "avg_saturation": 0.0,
    }


def test_basic_analysis_preserves_color_and_edge_classes(tmp_path):
    vivid = _save_jpeg(tmp_path, "vivid.jpg", Image.new("RGB", (320, 240), (255, 0, 0)))
    stripes = Image.new("RGB", (320, 240))
    stripes.putdata([
        (255, 255, 255) if x % 2 else (0, 0, 0)
        for _y in range(240)
        for x in range(320)
    ])
    action = _save_jpeg(tmp_path, "action.jpg", stripes)

    assert _analyse_frame_basic(str(vivid))["mood"] == "vivid"
    assert _analyse_frame_basic(str(action))["complexity"] == "action"


def test_basic_analysis_degrades_cleanly_for_malformed_image(tmp_path):
    malformed = tmp_path / "frame.jpg"
    malformed.write_bytes(b"not an image")

    assert _analyse_frame_basic(str(malformed)) == {
        "brightness": "unknown", "mood": "unknown", "complexity": "unknown",
    }
