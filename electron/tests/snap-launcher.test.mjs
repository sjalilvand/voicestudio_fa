import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { addSnapSandboxPreflight } from '../snap-launcher.mjs';

function launch(status, locale = 'en_US.UTF-8', args = [], dialog = true) {
  const dir = mkdtempSync(join(tmpdir(), 'snap-launcher-'));
  try {
    writeFileSync(join(dir, 'snapctl'), `#!/bin/sh\n[ "$*" = 'is-connected browser-support' ] || exit 99\nexit ${status}\n`, { mode: 0o755 });
    if (dialog) writeFileSync(join(dir, 'zenity'), '#!/bin/sh\nprintf "dialog:%s\\n" "$*" >&2\n', { mode: 0o755 });
    const script = addSnapSandboxPreflight('#!/bin/sh -e\nprintf "started:%s\\n" "$@"\n');
    return spawnSync('/bin/sh', ['-c', script, 'launcher', ...args], {
      env: { PATH: dir, LANG: locale }, encoding: 'utf8',
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test('disconnected sandbox stops Electron and explains the repair in terminal and dialog', () => {
  const result = launch(1);
  assert.equal(result.status, 1);
  assert.equal(result.stdout, '');
  assert.match(result.stderr, /sudo snap connect voicestudio:browser-support/);
  assert.match(result.stderr, /dialog:/);
});

test('connected sandbox preserves launch arguments', () => {
  const result = launch(0, 'en', ['a b', '--example']);
  assert.equal(result.status, 0);
  assert.equal(result.stdout, 'started:a b\nstarted:--example\n');
  assert.equal(result.stderr, '');
});

test('connection probe errors also stop startup', () => {
  assert.equal(launch(42).status, 1);
});

test('uses translated messages and falls back for unknown locales', () => {
  assert.match(launch(1, 'fr_FR.UTF-8').stderr, /autorisation/);
  assert.match(launch(1, 'xx_YY').stderr, /needs permission/);
});

test('packaging is idempotent and rejects invalid launchers', () => {
  const script = addSnapSandboxPreflight('#!/bin/sh\nexit 0\n');
  assert.equal(addSnapSandboxPreflight(script), script);
  assert.throws(() => addSnapSandboxPreflight('exit 0'), /shebang/);
});

test('terminal instructions remain available without a dialog tool', () => {
  const result = launch(1, 'en', [], false);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /sudo snap connect voicestudio:browser-support/);
  assert.doesNotMatch(result.stderr, /dialog:/);
});
