import { expect, it, vi } from 'vitest';

// account-ipc imports ../ipc, whose module graph reads Electron state at load.
vi.mock('electron', () => ({
  ipcMain: { handle: vi.fn(), removeHandler: vi.fn() },
  BrowserWindow: { getAllWindows: () => [] },
}));
vi.mock('../ipc', () => ({ assertTrustedMainFrame: vi.fn() }));
import { AccountController } from './account-ipc';

const TOKEN = 'eyJ-super-secret-token';
function ctl(over: Partial<ConstructorParameters<typeof AccountController>[0]> = {}) {
  const switches = { accountEnabled: true, syncEnabled: false, prompted: true };
  return new AccountController({
    available: true,
    switches: {
      get: () => ({ ...switches }),
      set: vi.fn((p) => Object.assign(switches, p)),
    } as never,
    session: {
      state: () => ({ signedIn: true, signingIn: false, notice: null }),
      getAccessToken: async () => ({ access_token: TOKEN, expires_at: 1 }),
    } as never,
    api: {
      get: async () => ({
        email: 'ana@example.com',
        displayName: 'Ana',
        avatarUrl: null,
        organizations: [],
      }),
      avatar: async () => null,
    } as never,
    remembered: true,
    ...over,
  });
}

it('the public state never carries a token', async () => {
  const s = await ctl().publicState();
  expect(JSON.stringify(s)).not.toContain(TOKEN);
  expect(Object.keys(s).sort()).toEqual([
    'accountEnabled',
    'available',
    'notice',
    'profile',
    'prompted',
    'remembered',
    'signedIn',
    'signingIn',
    'syncEnabled',
  ]);
});

it('an unavailable build reports off and makes no account call', async () => {
  const get = vi.fn();
  const s = await ctl({ available: false, api: { get } as never }).publicState();
  expect(s).toMatchObject({ available: false, accountEnabled: false, signedIn: false });
  expect(get).not.toHaveBeenCalled();
});

it('does not fetch the profile while account features are off', async () => {
  const get = vi.fn();
  const c = ctl({ api: { get } as never });
  await c.setSwitches({ accountEnabled: false });
  await c.publicState();
  expect(get).not.toHaveBeenCalled();
});

it('setSwitches validates input and always marks the prompt as answered', async () => {
  const c = ctl();
  await expect(c.setSwitches({ accountEnabled: 'yes' } as never)).rejects.toThrow(/Invalid/);
  const s = await c.setSwitches({ accountEnabled: false });
  expect(s.prompted).toBe(true);
});

it('the renderer gets the photo as a data URL, never the signed download link', async () => {
  const c = ctl({
    api: {
      get: async () => ({
        email: 'ana@example.com',
        displayName: 'Ana',
        avatarUrl: 'https://app-s3.voicestudio.sh/a.png?X-Amz-Signature=secret',
        personalOrganizationId: 'Or1',
        organizations: [],
      }),
      avatar: async () => 'data:image/png;base64,AAAA',
    } as never,
  });
  const s = await c.publicState(true);
  expect(s.profile?.avatarUrl).toBe('data:image/png;base64,AAAA');
  expect(JSON.stringify(s)).not.toContain('X-Amz-Signature');
});
