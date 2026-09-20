"""Exercise uv's actual constraints parser without downloads or installations."""
import importlib
import shutil
import subprocess
import sys

import pytest


def test_managed_constraints_with_spaces_reach_uv(tmp_path):
    uv = shutil.which('uv')
    if not uv:
        pytest.skip('uv is not installed')
    si = importlib.import_module('services.sidecar_install')
    checkout = tmp_path / 'Application Support' / 'dots #1'
    constraints = checkout / 'constraints' / 'recommended.txt'
    constraints.parent.mkdir(parents=True)
    constraints.write_text('six==1.17.0\n')
    requirements = tmp_path / 'empty.txt'
    requirements.write_text('')
    args = [si._expand(arg, checkout) for arg in si.get_spec('dots-tts').install_args]
    argument = args[args.index('-c') + 1]
    result = subprocess.run(
        [uv, 'pip', 'install', '--python', sys.executable, '--offline',
         '--no-index', '--dry-run', '-c', argument, '-r', str(requirements)],
        capture_output=True, text=True, timeout=30,
        env=si.uv_subprocess_env(tmp_path),
    )
    assert result.returncode == 0, result.stderr


def test_lazy_bootstrap_encodes_constraints_path(monkeypatch, tmp_path):
    bootstrap = importlib.import_module('engines.dots_tts.bootstrap')
    clone = tmp_path / 'Application Support' / 'dots #1'
    constraints = clone / 'constraints' / 'recommended.txt'
    constraints.parent.mkdir(parents=True)
    constraints.write_text('six==1.17.0\n')
    commands = []
    monkeypatch.setattr(bootstrap, '_locate_uv', lambda: 'uv')
    monkeypatch.setattr(bootstrap, '_ENGINES_VENV_DIR', tmp_path / 'venv')
    monkeypatch.setattr(bootstrap, '_venv_can_import_dots', lambda _: 'yes')
    monkeypatch.setattr(bootstrap.subprocess, 'run', lambda argv, **kw: commands.append(argv))
    bootstrap._bootstrap_engines_venv(clone)
    install = next(argv for argv in commands if argv[1:3] == ['pip', 'install'])
    assert install[install.index('-c') + 1] == constraints.as_uri()
