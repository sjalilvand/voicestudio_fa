"""Exercise actual ASR loaders with a verified fake Windows HIP CT2 runtime."""
import builtins
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch  # noqa: F401 - load before the fixture replaces package discovery.
from services import asr_backend as ab


# CLEAN-ROOM (spec W11-residue §T17): hip fixture: a verified fake Windows HIP CTranslate2 runtime


def test_faster_whisper_actually_loads_verified_hip(hip):
    assert ab.FasterWhisperBackend.is_available()[0]
    engine = ab.FasterWhisperBackend()
    engine._ensure_model()
    assert hip.loads == [{"device": "cuda", "compute_type": "float16"}]
    assert engine._device == "cuda"


@pytest.mark.parametrize("failure", ["binary", "count", "precision", "version"])
def test_stock_or_unusable_ct2_never_gets_hip_gpu(hip, monkeypatch, failure):
    if failure == "binary":
        monkeypatch.setattr(hip.ct2, "sha256", lambda path: "stock-cuda")
    elif failure == "count":
        hip.native.get_cuda_device_count = lambda: 0
    elif failure == "precision":
        hip.native.get_supported_compute_types = lambda device: {"int8"}
    else:
        monkeypatch.setattr(hip.ct2.metadata, "version", lambda name: "4.4.0")
    ab.FasterWhisperBackend()._ensure_model()
    assert hip.loads == [{"device": "cpu", "compute_type": "int8"}]


def test_explicit_cpu_override_stays_cpu(hip):
    hip.caps.family = "cpu"
    ab.FasterWhisperBackend()._ensure_model()
    assert hip.loads == [{"device": "cpu", "compute_type": "int8"}]


def test_cpu_auto_and_profile_never_probe_gpu(hip, monkeypatch):
    hip.caps.family = "cpu"
    monkeypatch.setattr(hip.ct2, "verify_environment", lambda: pytest.fail("CPU selection probed GPU"))
    monkeypatch.setattr(ab, "_mps_available", lambda: False)
    monkeypatch.setattr(ab, "_rocm_torch", lambda: False)
    monkeypatch.setattr(ab, "_probe_available", lambda cls: cls.id == "faster-whisper")
    assert ab._auto_detect() == "faster-whisper"
    assert "rocm" not in ab.FasterWhisperBackend.runtime_gpu_compat()


def test_auto_prefers_verified_windows_ct2_over_heavy_pytorch(hip, monkeypatch):
    monkeypatch.setattr(ab, "_mps_available", lambda: False)
    monkeypatch.setattr(ab, "_rocm_torch", lambda: True)
    monkeypatch.setattr(ab, "_cuda_reported_available", lambda: True)
    monkeypatch.setattr(ab, "_probe_available", lambda cls: True)
    assert ab._auto_detect() == "faster-whisper"


def test_isolated_worker_uses_same_verified_hip_gate(hip, monkeypatch):
    from core import execstack

    monkeypatch.setattr(execstack, "ensure_ctranslate2_loadable", lambda: (True, "ready"))
    path = Path(__file__).parents[1] / "backend/engines/_asr_sidecar/main.py"
    spec = importlib.util.spec_from_file_location("test_hip_asr_worker", path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    monkeypatch.setattr(worker, "_local_model_source", lambda name: "local", raising=False)
    worker._get_model()
    assert hip.loads[0]["device"] == "cuda"


def test_isolated_availability_initializes_dll_search(hip):
    from services.subprocess_asr import IsolatedFasterWhisperBackend

    assert IsolatedFasterWhisperBackend.is_available()[0]
    assert hip.ct2._VERIFIED  # Native discovery succeeded in the bounded child.


def test_runtime_gpu_metadata_admits_only_verified_hip(hip, monkeypatch):
    assert "rocm" in ab.FasterWhisperBackend.runtime_gpu_compat()
    monkeypatch.setattr(hip.ct2, "sha256", lambda path: "stock")
    assert "rocm" not in ab.FasterWhisperBackend.runtime_gpu_compat()


def test_actual_catalogue_and_execution_metadata_agree_on_hip(hip, monkeypatch):
    monkeypatch.setattr(ab, "_REGISTRY", {"faster-whisper": ab.FasterWhisperBackend})
    monkeypatch.setattr(ab, "_DEEP_IMPORT_BROKEN", {})
    row, = ab.list_backends()
    assert row["available"] and row["effective_device"] == "rocm"
    assert "rocm" in row["gpu_compat"]
    assert "rocm" in row["execution_evidence"]["declared_device_families"]


def test_linux_hip_and_cuda_existing_choices_preserved(hip, monkeypatch):
    monkeypatch.setattr(hip.ct2.sys, "platform", "linux")
    assert not ab._ctranslate2_cuda_ok()
    hip.caps.family = "cuda"
    monkeypatch.setattr(ab, "_cuda_reported_available", lambda: True)
    monkeypatch.setattr(ab, "_rocm_torch", lambda: False)
    assert ab._ctranslate2_cuda_ok()


@pytest.mark.parametrize("kind", ["timeout", "crash"])
def test_failed_native_child_never_imports_ct2_in_availability(hip, monkeypatch, kind):
    from services.subprocess_asr import IsolatedFasterWhisperBackend

    calls = []
    def fail():
        calls.append(True)
        if kind == "timeout":
            raise subprocess.TimeoutExpired("probe", 90)
        raise RuntimeError("native child exited -1073740791")

    monkeypatch.setattr(hip.ct2, "verify_environment", fail)
    imported = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in {"faster_whisper", "ctranslate2"}:
            pytest.fail("availability imported a native runtime after failed child")
        return imported(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    for cls in (ab.FasterWhisperBackend, IsolatedFasterWhisperBackend):
        ok, reason = cls.is_available()
        assert not ok and "Windows" in reason
        assert "rocm" not in cls.runtime_gpu_compat()
    assert len(calls) == 1, "one failed child must not repeat for every catalogue row/profile"
    monkeypatch.setattr(hip.ct2, "verify_environment", lambda: None)
    assert not hip.ct2.hip_ct2_available(), "a failed probe is not re-run on every refresh"
    hip.ct2._FAILED.clear()  # what a backend restart after rerunning setup does
    assert hip.ct2.hip_ct2_available(), "a fresh process verifies again"
