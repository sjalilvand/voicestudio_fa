"""The artifact rehearsal must exercise installation, not just the setup screen."""
from pathlib import Path

import yaml


def test_rehearsal_installs_runtime_in_a_separate_packaged_launch():
    workflow = yaml.safe_load(
        (Path(__file__).parents[1] / '.github/workflows/electron-build.yml').read_text()
    )
    steps = workflow['jobs']['package']['steps']
    runtime = [step for step in steps if '--install' in step.get('run', '')]
    assert len(runtime) == 1, 'Rehearsal must actually install and start the packaged runtime'
    assert runtime[0]['if'] == 'matrix.local_runtime'
    targets = workflow['jobs']['package']['strategy']['matrix']['include']
    assert {(t['platform'], t['arch']) for t in targets if t['local_runtime']} == {
        ('linux', 'x64'), ('win32', 'x64'), ('darwin', 'arm64'),
    }
    assert {(t['platform'], t['arch']) for t in targets if not t['local_runtime']} == {
        ('darwin', 'x64'),
    }
    assert '--setup' not in runtime[0]['run'], '--setup would bypass runtime installation'
    assert 'xvfb-run -a node tests/packaged-smoke.mjs --install' in runtime[0]['run']
    assert 'node tests/packaged-smoke.mjs --setup' in '\n'.join(s.get('run', '') for s in steps)
    assert workflow['permissions']['contents'] == 'read'
    assert '--publish never' in '\n'.join(s.get('run', '') for s in steps)
