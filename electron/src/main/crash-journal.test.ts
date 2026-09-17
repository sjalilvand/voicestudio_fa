// @vitest-environment node
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it } from 'vitest';
import { CrashJournal } from './crash-journal';
it('retains three bounded records across restart and ignores other versions without rewriting', () => {
  const path = join(mkdtempSync(join(tmpdir(), 'voice-crash-')), 'crashes.json');
  const journal = new CrashJournal(path, '1');
  for (let code = 1; code <= 4; code++)
    journal.record(code, null, 100, Array(45).fill('x'.repeat(5000)));
  const restored = new CrashJournal(path, '1').latest()!;
  expect(restored.exitCode).toBe(4);
  expect(restored.logTail).toHaveLength(40);
  expect(restored.logTail[0]).toHaveLength(4096);
  expect(restored.acknowledged).toBe(false);
  const saved = readFileSync(path, 'utf8');
  expect(JSON.parse(saved)).toHaveLength(3);
  expect(new CrashJournal(path, '2').latest()).toBeUndefined();
  expect(readFileSync(path, 'utf8')).toBe(saved);
});
it('retains acknowledged evidence across restart and resets seen state for a new crash', () => {
  const path = join(mkdtempSync(join(tmpdir(), 'voice-crash-')), 'crashes.json');
  const journal = new CrashJournal(path, '1');
  journal.record(1, null, 100, ['first']);
  expect(journal.acknowledgeLatest()?.acknowledged).toBe(true);
  expect(new CrashJournal(path, '1').latest()).toMatchObject({
    acknowledged: true,
    logTail: ['first'],
  });
  journal.record(2, null, 200, ['second']);
  expect(journal.latest()).toMatchObject({ exitCode: 2, acknowledged: false });
});
it('ignores port collisions and debugger exits, and tolerates corrupt or unwritable storage', () => {
  const path = join(mkdtempSync(join(tmpdir(), 'voice-crash-')), 'crashes.json');
  writeFileSync(path, 'corrupt');
  const journal = new CrashJournal(path, '1');
  journal.record(78, null, 0, []);
  journal.record(0x40010004, null, 0, []);
  expect(journal.latest()).toBeUndefined();
  expect(readFileSync(path, 'utf8')).toBe('corrupt');
  const inaccessible = new CrashJournal(join(path, 'child.json'), '1');
  inaccessible.record(null, 'SIGKILL', 3000, ['out of memory']);
  expect(inaccessible.latest()).toMatchObject({ signal: 'SIGKILL', uptimeMs: 3000 });
});
