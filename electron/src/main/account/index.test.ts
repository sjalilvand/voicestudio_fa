import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({
  packaged: false,
  dir: '',
  safeThrows: false,
  setBackendOnlyEnv: vi.fn(),
}));
vi.mock('electron', () => ({
  app: {
    get isPackaged() {
      return h.packaged;
    },
    getPath: () => h.dir,
  },
  safeStorage: {
    isEncryptionAvailable: () => {
      if (h.safeThrows) throw new Error('keychain locked');
      return false;
    },
    encryptString: (s: string) => Buffer.from(s),
    decryptString: (b: Buffer) => b.toString(),
  },
  shell: { openExternal: vi.fn() },
  ipcMain: { handle: vi.fn(), removeHandler: vi.fn() },
  BrowserWindow: { getAllWindows: () => [] },
}));
vi.mock('../backend', () => ({ setBackendOnlyEnv: h.setBackendOnlyEnv }));
vi.mock('../ipc', () => ({ assertTrustedMainFrame: vi.fn() }));

import { startAccount } from './index';

const opts = { getMainWindow: () => null, isRemoteBackend: () => false };
afterEach(() => {
  h.packaged = false;
  h.safeThrows = false;
  h.setBackendOnlyEnv.mockClear();
});

it('hands the bridge to the backend spawn only, never to process.env', async () => {
  h.dir = mkdtempSync(join(tmpdir(), 'vs-account-'));
  const close = await startAccount(opts);
  const vars = h.setBackendOnlyEnv.mock.calls[0][0];
  expect(vars.VOICESTUDIO_ACCOUNT_BRIDGE_URL).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
  expect(vars.VOICESTUDIO_ACCOUNT_BRIDGE_TOKEN).toMatch(/^[0-9a-f]{64}$/);
  expect(process.env.VOICESTUDIO_ACCOUNT_BRIDGE_TOKEN).toBeUndefined();
  close();
  expect(h.setBackendOnlyEnv).toHaveBeenLastCalledWith({
    VOICESTUDIO_ACCOUNT_BRIDGE_URL: undefined,
    VOICESTUDIO_ACCOUNT_BRIDGE_TOKEN: undefined,
  });
});

it('starts no bridge when the build does not offer accounts', async () => {
  h.packaged = true;
  h.dir = mkdtempSync(join(tmpdir(), 'vs-account-'));
  (await startAccount(opts))();
  expect(h.setBackendOnlyEnv).not.toHaveBeenCalled();
});

it('a startup failure degrades to no account features instead of blocking app start', async () => {
  h.safeThrows = true;
  h.dir = mkdtempSync(join(tmpdir(), 'vs-account-'));
  const close = await startAccount(opts);
  expect(typeof close).toBe('function');
  close();
});
