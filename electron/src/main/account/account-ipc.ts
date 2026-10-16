import { BrowserWindow, ipcMain } from 'electron';
import { assertTrustedMainFrame } from '../ipc';
import { sendToLiveWindow } from '../window-safety';
import type { AccountApi, AccountProfile } from './account-api';
import type { AccountPublicState } from '../../preload/index.d';
import type { AccountSession } from './account-session';
import type { CloudSwitchStore, CloudSwitches } from './cloud-switches';

export const ACCOUNT_CHANNELS = {
  get: 'account:get',
  signIn: 'account:sign-in',
  cancelSignIn: 'account:cancel-sign-in',
  signOut: 'account:sign-out',
  setSwitches: 'account:set-switches',
  updateProfile: 'account:update-profile',
  state: 'account:state',
} as const;

export type { AccountPublicState };

export class AccountController {
  private profile: AccountProfile | null = null;

  constructor(
    private readonly parts: {
      available: boolean;
      switches: CloudSwitchStore;
      session: AccountSession;
      api: AccountApi;
      remembered: boolean;
    },
  ) {}

  async publicState(refreshProfile = false): Promise<AccountPublicState> {
    const { available, switches, session, remembered } = this.parts;
    const sw: CloudSwitches = available
      ? switches.get()
      : { accountEnabled: false, syncEnabled: false, prompted: true };
    const s =
      available && sw.accountEnabled
        ? session.state()
        : { signedIn: false, signingIn: false, notice: null };
    if (!s.signedIn) this.profile = null;
    else if (refreshProfile || !this.profile)
      this.profile = await this.parts.api.get().catch(() => this.profile);
    return { available, ...sw, remembered, ...s, profile: this.profile };
  }

  async setSwitches(raw: unknown): Promise<AccountPublicState> {
    const p = raw as Partial<CloudSwitches>;
    for (const key of ['accountEnabled', 'syncEnabled'] as const)
      if (p?.[key] !== undefined && typeof p[key] !== 'boolean')
        throw new Error('Invalid switches');
    if (this.parts.available)
      this.parts.switches.set({
        ...(p.accountEnabled !== undefined ? { accountEnabled: p.accountEnabled } : {}),
        ...(p.syncEnabled !== undefined ? { syncEnabled: p.syncEnabled } : {}),
        prompted: true,
      });
    return this.publicState();
  }

  async updateProfile(raw: unknown): Promise<AccountPublicState> {
    const name = (raw as { display_name?: unknown })?.display_name;
    if (typeof name !== 'string' || name.length > 200) throw new Error('Invalid display name');
    this.profile = await this.parts.api.patch({ display_name: name });
    return this.publicState();
  }
}

export function registerAccountIpc(
  ctl: AccountController,
  session: AccountSession,
  getMainWindow: () => BrowserWindow | null,
): () => void {
  // A declared function, not an arrow const: TS2775 forbids calling an assertion through an unannotated const.
  function trusted(event: Electron.IpcMainInvokeEvent): void {
    assertTrustedMainFrame(event, getMainWindow());
  }
  const broadcast = async () => {
    const s = await ctl.publicState();
    for (const win of BrowserWindow.getAllWindows())
      sendToLiveWindow(win, ACCOUNT_CHANNELS.state, s);
  };
  const unsubscribe = session.onChange(() => void broadcast());
  ipcMain.handle(ACCOUNT_CHANNELS.get, (e) => (trusted(e), ctl.publicState(true)));
  ipcMain.handle(ACCOUNT_CHANNELS.signIn, (e) => (trusted(e), session.signIn().catch(() => {})));
  ipcMain.handle(ACCOUNT_CHANNELS.cancelSignIn, (e) => (trusted(e), session.cancelSignIn()));
  ipcMain.handle(ACCOUNT_CHANNELS.signOut, async (e) => (trusted(e), await session.signOut()));
  ipcMain.handle(ACCOUNT_CHANNELS.setSwitches, async (e, raw) => {
    trusted(e);
    try {
      return await ctl.setSwitches(raw);
    } finally {
      void broadcast();
    }
  });
  ipcMain.handle(ACCOUNT_CHANNELS.updateProfile, (e, raw) => (trusted(e), ctl.updateProfile(raw)));
  return () => {
    unsubscribe();
    for (const channel of Object.values(ACCOUNT_CHANNELS)) ipcMain.removeHandler(channel);
  };
}
