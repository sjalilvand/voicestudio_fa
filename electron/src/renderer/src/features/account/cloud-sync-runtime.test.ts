import { afterEach, expect, it, vi } from 'vitest';
import { startCloudSyncRuntime } from './cloud-sync-runtime';

const SHORTCUT = 'voicestudio.shortcut.dictation';

function fakeApi(pulls: Array<{ seq: number; values: Array<{ key: string; value: unknown; raw: boolean }> }>) {
  const calls: Array<[string, RequestInit | undefined]> = [];
  const api = vi.fn(async (path: string, init?: RequestInit) => {
    calls.push([path, init]);
    if (path === '/api/cloud-sync/local/keys') return { keys: ['voicestudio.theme.v2', SHORTCUT] };
    if (path.startsWith('/api/cloud-sync/local?since=')) return pulls.shift() ?? { seq: 9, values: [] };
    return {};
  });
  return { api, calls };
}

let stop: (() => void) | undefined;
afterEach(() => {
  stop?.();
  stop = undefined;
  localStorage.clear();
  vi.useRealTimers();
});

it('mirrors current values, then each change, and applies pulled values', async () => {
  vi.useFakeTimers();
  localStorage.setItem('voicestudio.theme.v2', 'dark');
  const { api, calls } = fakeApi([{ seq: 3, values: [{ key: 'voicestudio.theme.v2', value: 'light', raw: true }] }]);
  const capture = { getShortcut: vi.fn(async () => ({ accelerator: 'CmdOrCtrl+Shift+Space', active: true })), setShortcut: vi.fn() };
  stop = await startCloudSyncRuntime({ api, capture, intervalMs: 1000 });
  const puts = () => calls.filter(([p, i]) => p === '/api/cloud-sync/local' && i?.method === 'PUT').map(([, i]) => JSON.parse(String(i!.body)));
  expect(puts()).toEqual([
    { key: 'voicestudio.theme.v2', value: 'dark', raw: true },
    { key: SHORTCUT, value: 'CmdOrCtrl+Shift+Space', raw: true },
  ]);
  await vi.advanceTimersByTimeAsync(1000);
  expect(localStorage.getItem('voicestudio.theme.v2')).toBe('light');
  expect(puts()).toHaveLength(2); // the pulled value is not echoed
  localStorage.setItem('voicestudio.theme.v2', 'system');
  expect(puts().at(-1)).toEqual({ key: 'voicestudio.theme.v2', value: 'system', raw: true });
});

it('applies a pulled shortcut through the capture bridge and keeps it when the OS refuses', async () => {
  vi.useFakeTimers();
  const { api, calls } = fakeApi([{ seq: 1, values: [{ key: SHORTCUT, value: 'CmdOrCtrl+Alt+D', raw: true }] }]);
  const capture = {
    getShortcut: vi.fn(async () => ({ accelerator: 'CmdOrCtrl+Shift+Space', active: true })),
    setShortcut: vi.fn(async () => ({ accelerator: 'CmdOrCtrl+Shift+Space', active: false, error: 'in use' })),
  };
  stop = await startCloudSyncRuntime({ api, capture, intervalMs: 1000 });
  await vi.advanceTimersByTimeAsync(1000);
  expect(capture.setShortcut).toHaveBeenCalledWith('CmdOrCtrl+Alt+D');
  await vi.advanceTimersByTimeAsync(1000);
  const shortcutPuts = calls.filter(([p, i]) => p === '/api/cloud-sync/local' && String(i?.body).includes(SHORTCUT));
  expect(shortcutPuts).toHaveLength(1); // the refused local value never overwrites the synced one
});

it('window focus asks for a sync round and stop removes everything', async () => {
  const { api, calls } = fakeApi([]);
  stop = await startCloudSyncRuntime({ api, intervalMs: 60_000 });
  window.dispatchEvent(new Event('focus'));
  expect(calls.some(([p]) => p === '/api/cloud-sync/run')).toBe(true);
  stop();
  stop = undefined;
  const count = calls.length;
  localStorage.setItem('voicestudio.theme.v2', 'dark');
  window.dispatchEvent(new Event('focus'));
  expect(calls.length).toBe(count);
});
