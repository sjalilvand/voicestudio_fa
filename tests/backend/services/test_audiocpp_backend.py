"""Tests for the audio.cpp TTS backend (Breeze-TTS-2 over loopback HTTP).

Hermetic by design: every test exercises pure builders, env-driven
resolution, or registry wiring. No binary, no network, no model download —
``resolve_server_binary`` is only asserted on its failure message, and the
host env is scrubbed of ``OMNIVOICE_AUDIOCPP_*`` overrides per test.
"""
from __future__ import annotations

import base64
import errno
import importlib
import io
import json
import os
import stat
import string
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def _resolve_app_modules():
    """Resolve application modules per test after isolation has been applied."""
    audiocpp = importlib.import_module("engines.audiocpp")
    return SimpleNamespace(
        audiocpp=audiocpp,
        bootstrap=importlib.import_module("engines.audiocpp.bootstrap"),
        tts_backend=importlib.import_module("services.tts_backend"),
    )


@pytest.fixture
def app_modules():
    return _resolve_app_modules()


@pytest.fixture(autouse=True)
def scrub_audiocpp_env(monkeypatch):
    for var in (
        "OMNIVOICE_AUDIOCPP_BIN",
        "OMNIVOICE_AUDIOCPP_DIR",
        "OMNIVOICE_AUDIOCPP_MODEL",
        "OMNIVOICE_AUDIOCPP_PACKAGE",
        "OMNIVOICE_AUDIOCPP_PORT",
        "OMNIVOICE_AUDIOCPP_ASSET",
    ):
        monkeypatch.delenv(var, raising=False)


# ── server config builder ──────────────────────────────────────────────────


def test_build_server_config_is_loopback_lazy_single_model(monkeypatch, app_modules):
    monkeypatch.setattr(app_modules.audiocpp, "_cpu_thread_count", lambda: 16)
    cfg = app_modules.audiocpp.build_server_config(
        model_id="breeze-tts-2",
        family="breeze_tts",
        model_path="/models/breeze-tts-2-q8_0.gguf",
        port=17860,
    )
    assert cfg["host"] == "127.0.0.1"
    assert cfg["port"] == 17860
    assert cfg["backend"] == "cpu"
    assert cfg["threads"] == 16
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


def test_build_speech_payload_minimal_design(app_modules):
    payload = app_modules.audiocpp.build_speech_payload(
        model_id="breeze-tts-2", text="Hello.",
    )
    assert payload == {
        "model": "breeze-tts-2",
        "input": "Hello.",
        "response_format": "json",
    }


def test_build_speech_payload_clone_maps_verified_fields(app_modules):
    payload = app_modules.audiocpp.build_speech_payload(
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


def test_build_speech_payload_reference_text_needs_ref_audio(app_modules):
    payload = app_modules.audiocpp.build_speech_payload(
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


def test_decode_speech_json_roundtrip_mono(app_modules):
    obj = _wav_json_bytes([0.0, 0.5, -0.5, 0.25], 24000)
    sr, wav = app_modules.audiocpp.decode_speech_json(obj)
    assert sr == 24000
    assert wav.ndim == 1 and len(wav) == 4
    assert abs(float(wav[1]) - 0.5) < 1e-4


def test_decode_speech_json_downmixes_stereo(app_modules):
    import numpy as np

    stereo = np.array([[0.5, -0.5], [0.5, -0.5]], dtype=np.float32)
    obj = _wav_json_bytes(stereo, 24000)
    sr, wav = app_modules.audiocpp.decode_speech_json(obj)
    assert sr == 24000
    assert wav.ndim == 1 and len(wav) == 2


def test_decode_speech_json_error_payload_raises(app_modules):
    with pytest.raises(ValueError, match="audio.cpp speech failed"):
        app_modules.audiocpp.decode_speech_json({"error": "model not loaded"})


# ── bootstrap resolution ───────────────────────────────────────────────────


def test_binary_name_exe_on_windows_only(app_modules):
    bootstrap = app_modules.bootstrap
    assert bootstrap.binary_name("windows-x64") == "audiocpp_server.exe"
    assert bootstrap.binary_name("linux-x64") == "audiocpp_server"
    assert bootstrap.binary_name("darwin-arm64") == "audiocpp_server"


def test_release_assets_have_complete_sha256_pins(app_modules):
    bootstrap = app_modules.bootstrap
    for filename, digest in bootstrap._ASSETS.values():
        assert filename
        assert len(digest) == 64
        assert set(digest) <= set(string.hexdigits)
    assert "cpu-portable" in bootstrap._ASSETS["windows-x64"][0]
    assert "ubuntu-x64-cpu" in bootstrap._ASSETS["linux-x64"][0]


def test_model_catalog_and_backend_share_immutable_revision(app_modules):
    from services.hf_revisions import revision_for

    bootstrap = app_modules.bootstrap
    assert revision_for(bootstrap.HF_MODEL_REPO) == bootstrap.HF_MODEL_REVISION


def test_server_port_default_and_overrides(monkeypatch, app_modules):
    bootstrap = app_modules.bootstrap
    assert bootstrap.server_port() == bootstrap.DEFAULT_PORT
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_PORT", "18081")
    assert bootstrap.server_port() == 18081
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_PORT", "bogus")
    assert bootstrap.server_port() == bootstrap.DEFAULT_PORT


def test_package_filename_default_and_override(monkeypatch, app_modules):
    bootstrap = app_modules.bootstrap
    assert bootstrap.package_filename() == bootstrap.DEFAULT_PACKAGE
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_PACKAGE", "breeze-tts-2-bf16.gguf")
    assert bootstrap.package_filename() == "breeze-tts-2-bf16.gguf"


def test_materialize_hf_symlink_keeps_gguf_suffix_without_copy(tmp_path, app_modules):
    bootstrap = app_modules.bootstrap
    blob = tmp_path / "content-addressed-blob"
    blob.write_bytes(b"GGUF test payload")
    snapshot = tmp_path / "breeze-tts-2-q8_0.gguf"
    snapshot.symlink_to(blob)

    materialized = bootstrap._materialize_gguf_cache_path(snapshot)

    assert materialized.suffix == ".gguf"
    assert not materialized.is_symlink()
    assert os.path.samefile(materialized, blob)


def test_materialize_rejects_extensionless_model(tmp_path, app_modules):
    bootstrap = app_modules.bootstrap
    model = tmp_path / "model-blob"
    model.write_bytes(b"GGUF test payload")

    with pytest.raises(RuntimeError, match="must be a .gguf file"):
        bootstrap._materialize_gguf_cache_path(model)


def test_materialize_replaces_preexisting_symlink_alias(tmp_path, app_modules):
    bootstrap = app_modules.bootstrap
    blob = tmp_path / "content-addressed-blob"
    blob.write_bytes(b"GGUF test payload")
    snapshot = tmp_path / "breeze-tts-2-q8_0.gguf"
    snapshot.symlink_to(blob)
    alias = snapshot.with_name(
        f".{snapshot.stem}-{bootstrap.HF_MODEL_REVISION[:12]}.audiocpp.gguf"
    )
    alias.symlink_to(blob)

    materialized = bootstrap._materialize_gguf_cache_path(snapshot)

    assert materialized == alias
    assert not materialized.is_symlink()
    assert os.path.samefile(materialized, blob)


def test_materialize_cross_filesystem_symlink_links_beside_target(
    tmp_path, monkeypatch, app_modules,
):
    bootstrap = app_modules.bootstrap
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    blob = source_dir / "content-addressed-blob"
    blob.write_bytes(b"GGUF test payload")
    link_dir = tmp_path / "link"
    link_dir.mkdir()
    snapshot = link_dir / "custom.gguf"
    snapshot.symlink_to(blob)
    real_link = os.link
    calls = 0

    def cross_filesystem_once(source, destination):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(errno.EXDEV, "cross-device link")
        return real_link(source, destination)

    monkeypatch.setattr(bootstrap.os, "link", cross_filesystem_once)

    materialized = bootstrap._materialize_gguf_cache_path(snapshot)

    assert materialized.parent == blob.parent
    assert materialized.suffix == ".gguf"
    assert not materialized.is_symlink()
    assert os.path.samefile(materialized, blob)


def test_file_override_materializes_hf_style_symlink(
    tmp_path, monkeypatch, app_modules,
):
    bootstrap = app_modules.bootstrap
    blob = tmp_path / "blob"
    blob.write_bytes(b"GGUF test payload")
    model = tmp_path / "custom.gguf"
    model.symlink_to(blob)
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_MODEL", str(model))

    resolved = bootstrap.resolve_model_file()

    assert resolved.suffix == ".gguf"
    assert not resolved.is_symlink()
    assert os.path.samefile(resolved, blob)


def test_directory_override_materializes_hf_style_symlink(
    tmp_path, monkeypatch, app_modules,
):
    bootstrap = app_modules.bootstrap
    blob = tmp_path / "blob"
    blob.write_bytes(b"GGUF test payload")
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    model = model_dir / bootstrap.DEFAULT_PACKAGE
    model.symlink_to(blob)
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_MODEL", str(model_dir))

    resolved = bootstrap.resolve_model_file()

    assert resolved.suffix == ".gguf"
    assert not resolved.is_symlink()
    assert os.path.samefile(resolved, blob)


def test_cached_model_resolution_is_strictly_offline(
    tmp_path, monkeypatch, app_modules,
):
    bootstrap = app_modules.bootstrap
    package_dir = tmp_path / bootstrap.PACKAGE_DIR
    package_dir.mkdir()
    model = package_dir / bootstrap.DEFAULT_PACKAGE
    model.write_bytes(b"GGUF test payload")
    calls = []

    def cached_snapshot(**kwargs):
        calls.append(kwargs)
        return str(tmp_path)

    monkeypatch.setattr("huggingface_hub.snapshot_download", cached_snapshot)

    assert bootstrap.resolve_model_file() == model
    assert calls == [{
        "repo_id": bootstrap.HF_MODEL_REPO,
        "revision": bootstrap.HF_MODEL_REVISION,
        "allow_patterns": [f"{bootstrap.PACKAGE_DIR}/{bootstrap.DEFAULT_PACKAGE}"],
        "local_files_only": True,
    }]


def test_missing_cached_model_requires_explicit_install(
    monkeypatch, app_modules,
):
    bootstrap = app_modules.bootstrap

    def cache_miss(**_kwargs):
        raise OSError("not cached")

    monkeypatch.setattr("huggingface_hub.snapshot_download", cache_miss)

    with pytest.raises(RuntimeError, match="Model Catalogue → Models"):
        bootstrap.resolve_model_file()


def test_resolve_server_binary_missing_gives_install_hint(
    tmp_path, monkeypatch, app_modules,
):
    bootstrap = app_modules.bootstrap
    # Point both env probes at nothing; the package bin/ is unpopulated in
    # a source checkout, so this must fail with guidance, not a bare error.
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_BIN", str(tmp_path / "nope"))
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_DIR", str(tmp_path / "nodir"))
    with pytest.raises(RuntimeError, match="docs/engines/audio-cpp.md") as exc:
        bootstrap.resolve_server_binary()
    assert bootstrap.default_asset()[1] in str(exc.value)


def test_resolve_server_binary_prefers_env_bin(tmp_path, monkeypatch, app_modules):
    bootstrap = app_modules.bootstrap
    fake = tmp_path / "audiocpp_server"
    fake.write_bytes(b"#!/bin/sh\n")
    if os.name != "nt":
        fake.chmod(0o755)
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_BIN", str(fake))
    assert bootstrap.resolve_server_binary() == fake


def test_resolve_server_binary_rejects_non_executable_posix(
    tmp_path, monkeypatch, app_modules,
):
    if os.name == "nt":
        pytest.skip("POSIX executable bits do not apply on Windows")
    bootstrap = app_modules.bootstrap
    fake = tmp_path / "audiocpp_server"
    fake.write_bytes(b"binary")
    fake.chmod(0o644)
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_BIN", str(fake))

    with pytest.raises(RuntimeError, match=r"chmod \+x audiocpp_server"):
        bootstrap.resolve_server_binary()

    assert bootstrap.is_installed() is False


def test_non_executable_explicit_binary_does_not_fall_through(
    tmp_path, monkeypatch, app_modules,
):
    if os.name == "nt":
        pytest.skip("POSIX executable bits do not apply on Windows")
    bootstrap = app_modules.bootstrap
    explicit = tmp_path / "explicit" / "audiocpp_server"
    explicit.parent.mkdir()
    explicit.write_bytes(b"binary")
    explicit.chmod(0o644)
    fallback_dir = tmp_path / "fallback"
    fallback_dir.mkdir()
    fallback = fallback_dir / "audiocpp_server"
    fallback.write_bytes(b"#!/bin/sh\n")
    fallback.chmod(0o755)
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_BIN", str(explicit))
    monkeypatch.setenv("OMNIVOICE_AUDIOCPP_DIR", str(fallback_dir))

    with pytest.raises(RuntimeError, match=r"chmod \+x audiocpp_server"):
        bootstrap.resolve_server_binary()
    assert bootstrap.is_installed() is False


# ── backend protocol + registry ────────────────────────────────────────────


def test_app_modules_are_resolved_at_test_time(monkeypatch):
    real_import = importlib.import_module
    imported = []

    def recording_import(name):
        imported.append(name)
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", recording_import)

    resolved = _resolve_app_modules()

    assert resolved.audiocpp is real_import("engines.audiocpp")
    assert imported == [
        "engines.audiocpp",
        "engines.audiocpp.bootstrap",
        "services.tts_backend",
    ]


def test_backend_metadata(app_modules):
    AudioCPPBackend = app_modules.audiocpp.AudioCPPBackend
    assert AudioCPPBackend.id == "audiocpp"
    assert AudioCPPBackend.supports_voice_design is True
    assert AudioCPPBackend.supports_cloning is True
    assert AudioCPPBackend.runs_out_of_process is True
    assert AudioCPPBackend._is_subprocess_isolated is True
    assert AudioCPPBackend.gpu_compat == ("cpu",)
    assert AudioCPPBackend.min_vram_gb == 0.0
    backend = AudioCPPBackend()
    assert backend.sample_rate == 24000
    assert backend.supported_languages == ["en", "zh"]
    assert "breeze_tts" in (backend.model_identity() or "")


def test_server_identity_rejects_unrelated_loopback_listener(
    monkeypatch, app_modules,
):
    backend = app_modules.audiocpp.AudioCPPBackend()
    backend._proc = Mock()
    backend._proc.poll.return_value = None
    backend._port = 17860
    backend._server_model_id = "breeze-tts-2-private-launch"
    monkeypatch.setattr(
        backend,
        "_get_json",
        lambda path: {"data": [{"id": "someone-elses-model"}]},
    )

    with pytest.raises(RuntimeError, match="did not prove"):
        backend._verify_server_identity()


def test_server_spawn_uses_contained_owner(tmp_path, monkeypatch, app_modules):
    backend = app_modules.audiocpp.AudioCPPBackend()
    binary = tmp_path / "audiocpp_server"
    binary.write_bytes(b"binary")
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    monkeypatch.setattr(app_modules.bootstrap, "resolve_server_binary", lambda: binary)
    monkeypatch.setattr(app_modules.bootstrap, "resolve_model_file", lambda: model)
    monkeypatch.setattr(app_modules.bootstrap, "server_port", lambda: 17860)
    monkeypatch.setattr(
        importlib.import_module("core.config"), "DATA_DIR", tmp_path / "data",
    )
    proc = Mock()
    proc.poll.return_value = None
    spawn = Mock(return_value=proc)
    monkeypatch.setattr(app_modules.audiocpp, "spawn_owned", spawn)
    monkeypatch.setattr(backend, "_wait_for_health", lambda: None)

    backend._ensure_loaded()

    spawn.assert_called_once()
    config = json.loads(backend._server_json.read_text())
    assert config["backend"] == "cpu"
    assert config["models"][0]["id"].startswith("breeze-tts-2-")
    assert config["models"][0]["id"] != "breeze-tts-2"
    if os.name != "nt":
        assert stat.S_IMODE(backend._server_json.stat().st_mode) == 0o600
    backend._proc = None


def test_generate_timeout_terminates_owned_server(monkeypatch, app_modules):
    backend = app_modules.audiocpp.AudioCPPBackend()

    def mark_loaded():
        backend._port = 17860
        backend._server_model_id = "breeze-tts-2-private-launch"

    monkeypatch.setattr(backend, "_ensure_loaded", mark_loaded)
    monkeypatch.setattr(
        backend, "_post_json", Mock(side_effect=TimeoutError("wedged")),
    )
    terminate = Mock()
    monkeypatch.setattr(backend, "_terminate_server", terminate)
    model_manager = importlib.import_module("services.model_manager")
    monkeypatch.setattr(
        model_manager, "generate_timeout_s",
        lambda text, execution_device: 100.0,
    )
    monkeypatch.setattr(model_manager, "GENERATE_PROGRESS_GRACE_S", 40.0)
    progress = Mock()
    monkeypatch.setattr(model_manager, "report_generate_progress", progress)
    monotonic = iter((10.0, 30.0))
    monkeypatch.setattr(
        app_modules.audiocpp.time, "monotonic", lambda: next(monotonic),
    )

    with pytest.raises(RuntimeError, match="timed out"):
        backend.generate("Hello from the timeout test.")

    assert backend._post_json.call_args.kwargs["timeout"] == 65.0
    progress.assert_called_once_with()
    terminate.assert_called_once_with()


def test_generate_uses_progress_lease_after_first_download(
    monkeypatch, app_modules,
):
    backend = app_modules.audiocpp.AudioCPPBackend()

    def mark_loaded():
        enter = next(monotonic)
        assert enter == 20.0
        backend._port = 17860
        backend._server_model_id = "breeze-tts-2-private-launch"

    monotonic = iter((10.0, 20.0, 130.0))
    monkeypatch.setattr(backend, "_ensure_loaded", mark_loaded)
    monkeypatch.setattr(
        backend, "_post_json", Mock(side_effect=TimeoutError("wedged")),
    )
    monkeypatch.setattr(backend, "_terminate_server", Mock())
    model_manager = importlib.import_module("services.model_manager")
    monkeypatch.setattr(
        model_manager, "generate_timeout_s",
        lambda text, execution_device: 100.0,
    )
    monkeypatch.setattr(model_manager, "GENERATE_PROGRESS_GRACE_S", 40.0)
    progress = Mock()
    monkeypatch.setattr(model_manager, "report_generate_progress", progress)
    monkeypatch.setattr(
        app_modules.audiocpp.time, "monotonic", lambda: next(monotonic),
    )

    with pytest.raises(RuntimeError, match="timed out"):
        backend.generate("Hello after a slow first download.")

    assert backend._post_json.call_args.kwargs["timeout"] == 25.0
    progress.assert_called_once_with()


def test_terminate_server_reaps_after_forced_kill(app_modules):
    backend = app_modules.audiocpp.AudioCPPBackend()
    proc = Mock()
    proc.wait.side_effect = [
        subprocess.TimeoutExpired("audiocpp_server", 5.0),
        0,
    ]
    backend._proc = proc

    backend._terminate_server()

    proc.terminate.assert_called_once_with()
    proc.kill.assert_called_once_with()
    assert proc.wait.call_count == 2
    assert backend._proc is None


def test_generate_rejects_empty_text_without_spawning(app_modules):
    AudioCPPBackend = app_modules.audiocpp.AudioCPPBackend
    backend = AudioCPPBackend()
    with pytest.raises(app_modules.audiocpp.TTSInputError):
        backend.generate("   ")


def test_unload_before_load_is_safe(app_modules):
    app_modules.audiocpp.AudioCPPBackend().unload()


def test_registry_resolves_audiocpp(app_modules):
    assert (
        app_modules.tts_backend.get_backend_class("audiocpp")
        is app_modules.audiocpp.AudioCPPBackend
    )


def test_is_available_false_without_binary_gives_reason(app_modules):
    ok, msg = app_modules.audiocpp.AudioCPPBackend.is_available()
    if ok:
        pytest.skip("audiocpp_server installed on this host")
    assert "audiocpp_server" in msg
    assert "audio-cpp.md" in msg


def test_is_available_requires_explicitly_installed_model(
    tmp_path, monkeypatch, app_modules,
):
    bootstrap = app_modules.bootstrap
    binary = tmp_path / "audiocpp_server"
    monkeypatch.setattr(bootstrap, "resolve_server_binary", lambda: binary)

    def missing_model():
        raise RuntimeError(
            "Breeze-TTS-2 is not installed. Install it from Model Catalogue → Models."
        )

    monkeypatch.setattr(bootstrap, "resolve_model_file", missing_model)

    ok, msg = app_modules.audiocpp.AudioCPPBackend.is_available()

    assert ok is False
    assert "Model Catalogue → Models" in msg


def test_is_available_requires_binary_and_model(tmp_path, monkeypatch, app_modules):
    bootstrap = app_modules.bootstrap
    binary = tmp_path / "audiocpp_server"
    model = tmp_path / "breeze-tts-2-q8_0.gguf"
    monkeypatch.setattr(bootstrap, "resolve_server_binary", lambda: binary)
    monkeypatch.setattr(bootstrap, "resolve_model_file", lambda: model)

    assert app_modules.audiocpp.AudioCPPBackend.is_available() == (True, "ready")


def test_install_hint_present(app_modules):
    assert "audiocpp" in app_modules.tts_backend._INSTALL_HINTS


def test_no_hf_token_in_module_source(app_modules):
    # The bootstrap downloads from GitHub + ungated HF; no token may ever be
    # interpolated into an error string this module surfaces to the UI.
    import pathlib

    for name in ("__init__.py", "bootstrap.py"):
        src = pathlib.Path(app_modules.bootstrap.__file__).parent.joinpath(name).read_text()
        assert "HF_TOKEN" not in src
        assert "Authorization" not in src
