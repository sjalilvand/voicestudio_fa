"""MCP output mode + the base-path boundary.

Pure helpers, no MCP SDK needed: how generate_speech hands audio back
(OMNIVOICE_MCP_OUTPUT_MODE) and how path-shaped inputs are confined to
OMNIVOICE_MCP_BASE_PATH. The tool closures themselves are exercised through
the shape helpers they delegate to, so these run without a backend.
"""
import base64
import os

os.environ.setdefault("OMNIVOICE_MODEL", "test")
os.environ.setdefault("OMNIVOICE_DISABLE_FILE_LOG", "1")

import pytest


# ── output mode ─────────────────────────────────────────────────────────────

def test_output_mode_defaults_to_resources(monkeypatch):
    from mcp_server import _output_mode
    monkeypatch.delenv("OMNIVOICE_MCP_OUTPUT_MODE", raising=False)
    assert _output_mode() == "resources"


@pytest.mark.parametrize("raw,expected", [
    ("files", "files"),
    ("FILES", "files"),
    (" both ", "both"),
    ("resources", "resources"),
    ("banana", "resources"),   # unrecognized falls back, never fails the tool
])
def test_output_mode_parses_and_falls_back(monkeypatch, raw, expected):
    from mcp_server import _output_mode
    monkeypatch.setenv("OMNIVOICE_MCP_OUTPUT_MODE", raw)
    assert _output_mode() == expected


# ── base path boundary ──────────────────────────────────────────────────────

def test_base_path_none_when_unset(monkeypatch):
    from mcp_server import _base_path
    monkeypatch.delenv("OMNIVOICE_MCP_BASE_PATH", raising=False)
    assert _base_path() is None


def test_resolve_refuses_paths_without_a_base(monkeypatch):
    from mcp_server import _resolve_under_base
    monkeypatch.delenv("OMNIVOICE_MCP_BASE_PATH", raising=False)
    with pytest.raises(ValueError, match="OMNIVOICE_MCP_BASE_PATH is not set"):
        _resolve_under_base("clip.wav")


def test_resolve_accepts_relative_and_absolute_inside(monkeypatch, tmp_path):
    from mcp_server import _resolve_under_base
    monkeypatch.setenv("OMNIVOICE_MCP_BASE_PATH", str(tmp_path))
    inside = tmp_path / "sub" / "clip.wav"
    assert _resolve_under_base("sub/clip.wav") == os.path.realpath(str(inside))
    assert _resolve_under_base(str(inside)) == os.path.realpath(str(inside))


def test_resolve_refuses_escape(monkeypatch, tmp_path):
    from mcp_server import _resolve_under_base
    base = tmp_path / "base"
    base.mkdir()
    monkeypatch.setenv("OMNIVOICE_MCP_BASE_PATH", str(base))
    with pytest.raises(ValueError, match="outside OMNIVOICE_MCP_BASE_PATH"):
        _resolve_under_base("../secret.wav")
    with pytest.raises(ValueError, match="outside OMNIVOICE_MCP_BASE_PATH"):
        _resolve_under_base(str(tmp_path / "secret.wav"))


# ── input lanes ─────────────────────────────────────────────────────────────

def test_read_input_requires_exactly_one_lane():
    from mcp_server import _read_input_audio
    raw, err = _read_input_audio(None, None)
    assert raw is None and "exactly one" in err
    raw, err = _read_input_audio("QUJD", "x.wav")
    assert raw is None and "exactly one" in err


def test_read_input_path_lane_reads_inside_base(monkeypatch, tmp_path):
    from mcp_server import _read_input_audio
    monkeypatch.setenv("OMNIVOICE_MCP_BASE_PATH", str(tmp_path))
    (tmp_path / "clip.wav").write_bytes(b"RIFFxxxxWAVE")
    raw, err = _read_input_audio(None, "clip.wav")
    assert err is None and raw == b"RIFFxxxxWAVE"


def test_read_input_path_lane_reports_missing_and_escaped(monkeypatch, tmp_path):
    from mcp_server import _read_input_audio
    monkeypatch.setenv("OMNIVOICE_MCP_BASE_PATH", str(tmp_path))
    raw, err = _read_input_audio(None, "nope.wav")
    assert raw is None and "no such file" in err
    raw, err = _read_input_audio(None, "../nope.wav")
    assert raw is None and "outside" in err


def test_read_input_path_lane_refused_without_base(monkeypatch, tmp_path):
    from mcp_server import _read_input_audio
    monkeypatch.delenv("OMNIVOICE_MCP_BASE_PATH", raising=False)
    raw, err = _read_input_audio(None, str(tmp_path / "clip.wav"))
    assert raw is None and "is not set" in err


def test_read_input_base64_lane_keeps_data_uri_tolerance_and_labels():
    from mcp_server import _read_input_audio
    body = base64.b64encode(b"RIFFxxxxWAVE").decode()
    raw, err = _read_input_audio(f"data:audio/wav;base64,{body}", None)
    assert err is None and raw == b"RIFFxxxxWAVE"
    raw, err = _read_input_audio("not!!base64", None, label="ref_audio_base64")
    assert raw is None and err == "ref_audio_base64 is not valid base64"


# ── the generate_speech reply shape ─────────────────────────────────────────

def test_speech_result_resources_is_the_original_contract(monkeypatch):
    from mcp_server import _speech_result
    monkeypatch.setenv("OMNIVOICE_MCP_OUTPUT_MODE", "resources")
    out = _speech_result("ab12cd34", 1.5, 2.0, b"RIFF", "http://localhost:3900")
    assert out["wav_base64"] == base64.b64encode(b"RIFF").decode()
    assert "audio_url" not in out and "output_path" not in out
    assert out["output_mode"] == "resources"


def test_speech_result_files_returns_url_and_writes_under_base(monkeypatch, tmp_path):
    from mcp_server import _speech_result
    monkeypatch.setenv("OMNIVOICE_MCP_OUTPUT_MODE", "files")
    monkeypatch.setenv("OMNIVOICE_MCP_BASE_PATH", str(tmp_path))
    out = _speech_result("ab12cd34", 1.5, 2.0, b"RIFF", "http://localhost:3900/")
    assert out["audio_url"] == "http://localhost:3900/audio/ab12cd34.wav"
    assert "wav_base64" not in out
    written = out["output_path"]
    assert os.path.dirname(os.path.realpath(written)) == os.path.realpath(str(tmp_path))
    with open(written, "rb") as f:
        assert f.read() == b"RIFF"


def test_speech_result_files_without_base_is_url_only_with_a_note(monkeypatch):
    from mcp_server import _speech_result
    monkeypatch.setenv("OMNIVOICE_MCP_OUTPUT_MODE", "files")
    monkeypatch.delenv("OMNIVOICE_MCP_BASE_PATH", raising=False)
    out = _speech_result("ab12cd34", 1.5, 2.0, b"RIFF", "http://localhost:3900")
    assert out["audio_url"].endswith("/audio/ab12cd34.wav")
    assert "output_path" not in out and "OMNIVOICE_MCP_BASE_PATH" in out["note"]
    assert "wav_base64" not in out


def test_speech_result_both_carries_everything(monkeypatch, tmp_path):
    from mcp_server import _speech_result
    monkeypatch.setenv("OMNIVOICE_MCP_OUTPUT_MODE", "both")
    monkeypatch.setenv("OMNIVOICE_MCP_BASE_PATH", str(tmp_path))
    out = _speech_result("ab12cd34", "?", "?", b"RIFF", "http://localhost:3900")
    assert {"wav_base64", "audio_url", "output_path"} <= set(out)
    assert out["generation_time_s"] == "?"   # header text passes through untouched


@pytest.mark.parametrize("raw,expected", [
    (None, 120.0),
    ("600", 600.0),
    ("0", 120.0),        # non-positive falls back
    ("soon", 120.0),     # garbage falls back, never fails the tool
])
def test_post_timeout_reads_env_with_fallbacks(monkeypatch, raw, expected):
    from mcp_server import _post_timeout_s
    if raw is None:
        monkeypatch.delenv("OMNIVOICE_MCP_TIMEOUT_S", raising=False)
    else:
        monkeypatch.setenv("OMNIVOICE_MCP_TIMEOUT_S", raw)
    assert _post_timeout_s() == expected


def test_maybe_number_keeps_header_text_honest():
    from mcp_server import _maybe_number
    assert _maybe_number("1.25") == 1.25
    assert _maybe_number("?") == "?"
    assert _maybe_number(None) is None
