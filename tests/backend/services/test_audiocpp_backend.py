"""Tests for the audio.cpp TTS backend (Breeze-TTS-2 over loopback HTTP).

Hermetic by design: every test exercises pure builders, env-driven
resolution, or registry wiring. No binary, no network, no model download —
``resolve_server_binary`` is only asserted on its failure message, and the
host env is scrubbed of ``OMNIVOICE_AUDIOCPP_*`` overrides per test.
"""
from __future__ import annotations

import base64
import string
import io
import os
import tarfile
import zipfile

import pytest

# tests/conftest.py prepends ./backend to sys.path so these resolve.
from engines.audiocpp import (
    AudioCPPBackend,
    build_server_config,
    build_speech_payload,
    decode_speech_json,
)
from engines.audiocpp import bootstrap
from services.tts_backend import TTSInputError, get_backend_class


@pytest.fixture(autouse=True)
def scrub_audiocpp_env(monkeypatch):
    for var in (
        "OMNIVOICE_AUDIOCPP_BIN",
        "OMNIVOICE_AUDIOCPP_DIR",
        "OMNIVOICE_AUDIOCPP_MODEL",
        "OMNIVOICE_AUDIOCPP_PACKAGE",
        "OMNIVOICE_AUDIOCPP_BACKEND",
        "OMNIVOICE_AUDIOCPP_PORT",
        "OMNIVOICE_AUDIOCPP_ASSET",
    ):
        monkeypatch.delenv(var, raising=False)


# ── server config builder ──────────────────────────────────────────────────


def test_build_server_config_is_loopback_lazy_single_model():
    cfg = build_server_config(
        model_id="breeze-tts-2",
        family="breeze_tts",
        model_path="/models/breeze-tts-2-q8_0.gguf",
        backend="vulkan",
        port=17860,
    )
    assert cfg["host"] == "127.0.0.1"
    assert cfg["port"] == 17860
    assert cfg["backend"] == "vulkan"
    assert cfg["lazy_load"] is True
    assert cfg["max_loaded_models"] == 1
    assert cfg["models"] == [
        {
            "id": "breeze-tts-2",
            "family": "breeze_tts",
            "path": "/models/breeze-tts-2-q8_0.gguf",
            "task": "tts",
            "mode": "offline",
        }
    ]


# ── speech payload builder ─────────────────────────────────────────────────


def test_build_speech_payload_minimal_design():
    payload = build_speech_payload(model_id="breeze-tts-2", text="Hello.")
    assert payload == {
        "model": "breeze-tts-2",
        "input": "Hello.",
        "response_format": "json",
    }


def test_build_speech_payload_clone_maps_verified_fields():
    payload = build_speech_payload(
        model_id="breeze-tts-2",
        text="Read this.",
        ref_audio="/voices/alice.wav",
        ref_text="Exact transcript.",
        instructions="Speak slowly.",
        guidance_scale=4.0,
        seed=42,
    )
    assert payload["instructions"] == "Speak slowly."
    assert payload["voice_ref"] == {"type": "path", "path": "/voices/alice.wav"}
    assert payload["reference_text"] == "Exact transcript."
    assert payload["guidance_scale"] == 4.0
    assert payload["seed"] == 42


def test_build_speech_payload_reference_text_needs_ref_audio():
    payload = build_speech_payload(
        model_id="breeze-tts-2", text="Hi.", ref_text="stray transcript",
    )
    assert "reference_text" not in payload
    assert "voice_ref" not in payload


# ── speech reply decoder ───────────────────────────────────────────────────


def _wav_json_bytes(mono, sr):
    import numpy as np
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, np.asarray(mono, dtype=np.float32), sr, format="WAV")
    return {"audio": base64.b64encode(buf.getvalue()).decode("ascii")}


def test_decode_speech_json_roundtrip_mono():
    obj = _wav_json_bytes([0.0, 0.5, -0.5, 0.25], 24000)
    sr, wav = decode_speech_json(obj)
    assert sr == 24000
    assert wav.ndim == 1 and len(wav) == 4
    assert abs(float(wav[1]) - 0.5) < 1e-4


def test_decode_speech_json_downmixes_stereo():
    import numpy as np

    stereo = np.array([[0.5, -0.5], [0.5, -0.5]], dtype=np.float32)
    obj = _wav_json_bytes(stereo, 24000)
    sr, wav = decode_speech_json(obj)
    assert sr == 24000
    assert wav.ndim == 1 and len(wav) == 2


def test_decode_speech_json_error_payload_raises():
    with pytest.raises(ValueError, match="audio.cpp speech failed"):
        decode_speech_json({"error": "model not loaded"})


# ── bootstrap resolution ───────────────────────────────────────────────────


def test_binary_name_exe_on_windows_only():
    assert bootstrap.binary_name("windows-x64") == "audiocpp_server.exe"
    assert bootstrap.binary_name("linux-x64") == "audiocpp_server"
    assert bootstrap.binary_name("darwin-arm64") == "audiocpp_server"


def test_release_assets_have_complete_sha256_pins():
    for filename, digest in bootstrap._ASSETS.values():
        assert filename
        assert len(digest) == 64
        assert set(digest) <= set(string.hexdigits)


def test_server_port_default_and_overrides(monkeypatch):
    assert bootstrap.server_port() == bootstrap.DEFAULT_PORT
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_PORT", "18081")
    assert bootstrap.server_port() == 18081
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_PORT", "bogus")
    assert bootstrap.server_port() == bootstrap.DEFAULT_PORT


def test_package_filename_default_and_override(monkeypatch):
    assert bootstrap.package_filename() == bootstrap.DEFAULT_PACKAGE
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_PACKAGE", "breeze-tts-2-bf16.gguf")
    assert bootstrap.package_filename() == "breeze-tts-2-bf16.gguf"


def test_materialize_hf_symlink_keeps_gguf_suffix_without_copy(tmp_path):
    blob = tmp_path / "content-addressed-blob"
    blob.write_bytes(b"GGUF test payload")
    snapshot = tmp_path / "breeze-tts-2-q8_0.gguf"
    snapshot.symlink_to(blob)

    materialized = bootstrap._materialize_gguf_cache_path(snapshot)

    assert materialized.suffix == ".gguf"
    assert not materialized.is_symlink()
    assert os.path.samefile(materialized, blob)


def test_materialize_rejects_extensionless_model(tmp_path):
    model = tmp_path / "model-blob"
    model.write_bytes(b"GGUF test payload")

    with pytest.raises(RuntimeError, match="must be a .gguf file"):
        bootstrap._materialize_gguf_cache_path(model)


def test_default_backend_env_override(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_BACKEND", "cpu")
    assert bootstrap.default_backend() == "cpu"


def test_resolve_server_binary_missing_gives_install_hint(tmp_path, monkeypatch):
    # Point both env probes at nothing; the package bin/ is unpopulated in
    # a source checkout, so this must fail with guidance, not a bare error.
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_BIN", str(tmp_path / "nope"))
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_DIR", str(tmp_path / "nodir"))
    with pytest.raises(RuntimeError, match="docs/engines/audio-cpp.md"):
        bootstrap.resolve_server_binary()


def test_resolve_server_binary_prefers_env_bin(tmp_path, monkeypatch):
    fake = tmp_path / "audiocpp_server"
    fake.write_bytes(b"#!/bin/sh\n")
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_BIN", str(fake))
    assert bootstrap.resolve_server_binary() == fake


def test_release_zip_rejects_path_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape", b"nope")

    with pytest.raises(RuntimeError, match="unsafe audio.cpp archive member"):
        bootstrap._extract_release_archive(archive, archive.name, tmp_path / "out")
    assert not (tmp_path / "escape").exists()


def test_release_tar_rejects_links(tmp_path):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        member = tarfile.TarInfo("server-link")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        tf.addfile(member)

    with pytest.raises(RuntimeError, match="unsafe audio.cpp archive member type"):
        bootstrap._extract_release_archive(archive, archive.name, tmp_path / "out")


# ── backend protocol + registry ────────────────────────────────────────────


def test_backend_metadata():
    assert AudioCPPBackend.id == "audiocpp"
    assert AudioCPPBackend.supports_voice_design is True
    assert AudioCPPBackend.supports_cloning is True
    assert AudioCPPBackend.runs_out_of_process is True
    assert AudioCPPBackend._is_subprocess_isolated is True
    backend = AudioCPPBackend()
    assert backend.sample_rate == 24000
    assert backend.supported_languages == ["en", "zh"]
    assert "breeze_tts" in (backend.model_identity() or "")


def test_generate_rejects_empty_text_without_spawning():
    backend = AudioCPPBackend()
    with pytest.raises(TTSInputError):
        backend.generate("   ")


def test_unload_before_load_is_safe():
    AudioCPPBackend().unload()  # must never raise (idempotent contract)


def test_registry_resolves_audiocpp():
    assert get_backend_class("audiocpp") is AudioCPPBackend


def test_is_available_false_without_binary_gives_reason():
    ok, msg = AudioCPPBackend.is_available()
    if ok:
        pytest.skip("audiocpp_server installed on this host")
    assert "audiocpp_server" in msg
    assert "audio-cpp.md" in msg


def test_install_hint_present():
    from services import tts_backend

    assert "audiocpp" in tts_backend._INSTALL_HINTS


def test_no_hf_token_in_module_source():
    # The bootstrap downloads from GitHub + ungated HF; no token may ever be
    # interpolated into an error string this module surfaces to the UI.
    import pathlib

    for name in ("__init__.py", "bootstrap.py"):
        src = pathlib.Path(bootstrap.__file__).parent.joinpath(name).read_text()
        assert "HF_TOKEN" not in src
        assert "Authorization" not in src
