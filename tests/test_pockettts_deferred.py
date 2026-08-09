"""PocketTTS first-use gate and model-free sidecar integration (#1442)."""
from __future__ import annotations

import sys
import types

import pytest
from engines.pockettts import PocketTTSBackend


STUB_SIDECAR = r'''
import base64, json, struct, sys

def send(obj):
    body = json.dumps(obj, separators=(",", ":")).encode()
    sys.stdout.buffer.write(struct.pack("!I", len(body)) + body)
    sys.stdout.buffer.flush()

def recv():
    header = sys.stdin.buffer.read(4)
    if len(header) != 4:
        return None
    length = struct.unpack("!I", header)[0]
    return json.loads(sys.stdin.buffer.read(length))

send({"op": "ready", "engine": "pockettts", "sample_rate": 24000})
while True:
    message = recv()
    if message is None or message.get("op") == "shutdown":
        break
    if message.get("op") == "ping":
        send({"op": "pong", "vram_mb": 0.0})
    elif message.get("op") == "synthesize":
        # Prove engine-specific kwargs cross the real subprocess wire.
        assert message.get("language") == "fr"
        assert message.get("ref_audio") == "/tmp/reference.wav"
        pcm = struct.pack("<4h", 0, 1000, -1000, 0)
        send({"op": "progress", "stage": "loading_model", "percent": 50})
        send({"op": "audio", "audio_pcm_b64": base64.b64encode(pcm).decode(),
              "sample_rate": 24000, "n_samples": 4})
'''


def test_license_gate_fails_closed_then_allows_engine(monkeypatch, mock_settings_store):
    monkeypatch.setitem(sys.modules, "pocket_tts", types.ModuleType("pocket_tts"))
    mock_settings_store.pop("pockettts", None)

    ok, reason = PocketTTSBackend.is_available()
    assert ok is False
    assert "license not accepted" in reason.lower()
    assert "Settings" in reason and "Engines" in reason

    mock_settings_store["pockettts"] = True
    assert PocketTTSBackend.is_available() == (True, "ready (CPU-only)")


def test_pockettts_is_a_pinned_optional_extra():
    import tomllib
    from pathlib import Path

    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8")
    )
    assert project["project"]["optional-dependencies"]["pockettts"] == [
        "pocket-tts==2.1.0 ; sys_platform != 'darwin' or platform_machine != 'x86_64'"
    ]


def test_pockettts_reports_the_intel_mac_wheel_gap(monkeypatch):
    monkeypatch.setattr("engines.pockettts.sys.platform", "darwin")
    monkeypatch.setattr("engines.pockettts.platform.machine", lambda: "x86_64")
    ok, reason = PocketTTSBackend.is_available()
    assert ok is False
    assert "Intel Macs" in reason
    assert "PyTorch" in reason


def test_ci_verifies_intel_mac_as_the_documented_remote_only_host():
    from pathlib import Path

    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(
        "utf-8"
    )
    assert "label: macOS Intel\n            backend_supported: false" in workflow
    assert "name: Verify the documented Intel Mac contract" in workflow
    assert "if: matrix.backend_supported\n        run: uv sync --extra pockettts" in workflow
    assert "if: matrix.backend_supported\n        run: uv run pytest tests/smoke/" in workflow


@pytest.mark.parametrize(
    "reason",
    [
        "Cannot access gated repo for model kyutai/pocket-tts",
        "PocketTTS requires you to share your contact information",
        "Kyutai Pocket TTS access agreement has not been accepted",
    ],
)
def test_gated_weight_failures_are_typed_and_actionable(reason):
    from core.failure import build_failure, classify

    assert classify(reason) == "POCKETTTS_GATED_WEIGHTS"
    failure = build_failure(reason, stage="model_load", include_diagnostic=False)
    assert failure["docs_topic"] == "POCKETTTS_GATED_WEIGHTS"
    assert "huggingface.co/kyutai/pocket-tts" in failure["hint"]
    assert "HF_TOKEN" in failure["hint"]


def test_generic_gated_model_still_uses_existing_pyannote_class():
    from core.failure import classify

    assert classify("gated model license not accepted") == "PYANNOTE_LICENSE_REQUIRED"


def test_license_gate_fails_closed_when_settings_read_fails(monkeypatch):
    monkeypatch.setitem(sys.modules, "pocket_tts", types.ModuleType("pocket_tts"))
    from services import settings_store
    monkeypatch.setattr(settings_store, "get_license_accepted", lambda _eid: (_ for _ in ()).throw(OSError("db unavailable")))
    assert PocketTTSBackend.is_available()[0] is False


def test_stub_sidecar_roundtrip_is_model_free_and_forwards_voice_inputs(tmp_path, monkeypatch):
    stub = tmp_path / "pockettts_stub.py"
    stub.write_text(STUB_SIDECAR, encoding="utf-8")
    monkeypatch.setattr(PocketTTSBackend, "sidecar_script", classmethod(lambda cls: stub))
    # Use this interpreter while retaining the engine's real override surface.
    monkeypatch.setattr(PocketTTSBackend, "venv_python", classmethod(lambda cls: __import__("pathlib").Path(sys.executable)))

    backend = PocketTTSBackend()
    try:
        audio = backend.generate(
            "bonjour", language="fr", ref_audio="/tmp/reference.wav"
        )
        assert tuple(audio.shape) == (1, 4)
        assert audio[0, 1].item() == pytest.approx(1000 / 32768.0)
    finally:
        backend.shutdown()


def test_license_api_accepts_pockettts_and_rejects_unknown(settings_mod, mock_settings_store):
    body = settings_mod._LicenseAcceptBody(engine_id=" PocketTTS ", accepted=True)
    assert settings_mod.post_license_acceptance(body) == {
        "ok": True, "engine_id": "pockettts", "accepted": True
    }
    assert mock_settings_store["pockettts"] is True

    with pytest.raises(Exception) as exc:
        settings_mod.post_license_acceptance(
            settings_mod._LicenseAcceptBody(engine_id="unknown", accepted=True)
        )
    assert getattr(exc.value, "status_code", None) == 400


@pytest.fixture
def settings_mod():
    import importlib
    return importlib.import_module("api.routers.settings")
