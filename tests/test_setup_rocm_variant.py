"""Source-install ROCm torch handling in scripts/setup.py, and the no-sync dev launcher."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def setup_mod():
    spec = importlib.util.spec_from_file_location("setup_under_test", REPO / "scripts" / "setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestOptIn:
    @pytest.mark.parametrize("env", [{}, {"OMNIVOICE_TORCH_VARIANT": ""}, {"OMNIVOICE_TORCH_VARIANT": "cuda"},
                                     {"OMNIVOICE_TORCH_VARIANT": "auto"}])
    def test_not_requested(self, setup_mod, env):
        assert setup_mod._rocm_opt_in(env) is None

    def test_requested_with_odd_spelling(self, setup_mod):
        assert setup_mod._rocm_opt_in({"OMNIVOICE_TORCH_VARIANT": "\tRoCm\n"}) == setup_mod.ROCM_TORCH_INDEX

    def test_index_override_and_empty_override(self, setup_mod):
        env = {"OMNIVOICE_TORCH_VARIANT": "rocm", "OMNIVOICE_TORCH_INDEX": "https://wheels.invalid/amd"}
        assert setup_mod._rocm_opt_in(env) == "https://wheels.invalid/amd"
        env["OMNIVOICE_TORCH_INDEX"] = ""
        assert setup_mod._rocm_opt_in(env) == setup_mod.ROCM_TORCH_INDEX


def test_command_layout(setup_mod):
    assert setup_mod.ROCM_TORCH_PINS == ("torch==2.8.0", "torchaudio==2.8.0", "torchvision==0.23.0")
    cmd = setup_mod.rocm_torch_reinstall_cmd("https://wheels.invalid/x", python="/opt/venv/bin/py")
    assert cmd[:6] == ["uv", "pip", "install", "--reinstall", "--python", "/opt/venv/bin/py"]
    assert cmd[6:9] == list(setup_mod.ROCM_TORCH_PINS)
    assert cmd[9:] == ["--index-url", "https://wheels.invalid/x"]
    assert setup_mod.rocm_torch_reinstall_cmd("u")[5] == sys.executable


class _Recorder:
    def __init__(self, exc=None):
        self.cmds = []
        self.exc = exc

    def __call__(self, cmd, *a, **k):
        self.cmds.append(cmd)
        if self.exc:
            raise self.exc


def _arm(monkeypatch, mod, *, variant="rocm", already=False, exc=None):
    if variant is None:
        monkeypatch.delenv("OMNIVOICE_TORCH_VARIANT", raising=False)
    else:
        monkeypatch.setenv("OMNIVOICE_TORCH_VARIANT", variant)
    monkeypatch.delenv("OMNIVOICE_TORCH_INDEX", raising=False)
    monkeypatch.setattr(mod, "_installed_torch_is_rocm", lambda: already)
    rec = _Recorder(exc)
    monkeypatch.setattr(mod.subprocess, "check_call", rec)
    return rec


def test_swap_runs_once_when_needed(monkeypatch, setup_mod):
    rec = _arm(monkeypatch, setup_mod)
    setup_mod._ensure_rocm_torch()
    assert rec.cmds == [setup_mod.rocm_torch_reinstall_cmd(setup_mod.ROCM_TORCH_INDEX)]


@pytest.mark.parametrize("kwargs", [{"variant": None}, {"variant": "auto"}, {"already": True}])
def test_swap_skipped(monkeypatch, setup_mod, kwargs):
    rec = _arm(monkeypatch, setup_mod, **kwargs)
    setup_mod._ensure_rocm_torch()
    assert rec.cmds == []


@pytest.mark.parametrize("exc", [FileNotFoundError("uv"), subprocess.CalledProcessError(2, ["uv"])])
def test_swap_failure_only_warns(monkeypatch, capsys, setup_mod, exc):
    _arm(monkeypatch, setup_mod, exc=exc)
    setup_mod._ensure_rocm_torch()
    assert capsys.readouterr().out.strip() != ""


def test_probe_survives_broken_torch(monkeypatch, setup_mod):
    monkeypatch.setitem(sys.modules, "torch", None)
    assert setup_mod._installed_torch_is_rocm() is False


@pytest.mark.parametrize("plat, runs", [("linux", True), ("linux2", True), ("win32", False), ("darwin", False)])
def test_main_platform_gate(monkeypatch, setup_mod, plat, runs):
    monkeypatch.setattr(setup_mod.sys, "platform", plat)
    monkeypatch.setenv("OMNIVOICE_TORCH_VARIANT", "rocm")
    hits = []
    monkeypatch.setattr(setup_mod, "_ensure_rocm_torch", lambda: hits.append(1))
    monkeypatch.setattr(setup_mod, "_ensure_vcredist_windows", lambda: None)
    monkeypatch.setattr(setup_mod.subprocess, "check_call", lambda *a, **k: 0)
    monkeypatch.setattr(setup_mod, "_find_compat_dir", lambda: None)
    setup_mod.main()
    assert bool(hits) is runs


@pytest.mark.parametrize("variant", [None, "auto", " ROCm "])
def test_launcher_never_resyncs(variant):
    code = (
        "import * as m from './scripts/dev-backend.mjs';"
        "console.log(JSON.stringify({run: m.uvRunArgs(process.env), base: m.uvicornArgs({})}));"
    )
    env = {"PATH": os.environ["PATH"]}
    if variant is not None:
        env["OMNIVOICE_TORCH_VARIANT"] = variant
    res = subprocess.run(["node", "--input-type=module", "-e", code], cwd=REPO, env=env,
                         capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)
    expected = list(data["base"])
    expected.insert(1, "--no-sync")
    assert data["run"] == expected
