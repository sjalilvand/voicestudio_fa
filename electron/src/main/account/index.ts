import { join } from 'node:path';
import { app, safeStorage, shell, type BrowserWindow } from 'electron';
import { AccountApi } from './account-api';
import { AccountController, registerAccountIpc } from './account-ipc';
import { AccountSession } from './account-session';
import { startAccountTokenBridge } from './account-token-bridge';
import { CloudActivity } from './cloud-activity';
import { cloudAccountsAvailable, cloudOrigins, resolveCloudEnvironment } from './cloud-config';
import { CloudSwitchStore } from './cloud-switches';
import { startLoopback } from './loopback';
import { OidcClient } from './oidc';
import { RefreshTokenStore } from './token-store';
import { setBackendOnlyEnv } from '../backend';

interface StartOptions {
  getMainWindow: () => BrowserWindow | null;
  isRemoteBackend: () => boolean;
}

const BRIDGE_ENV_OFF = {
  VOICESTUDIO_ACCOUNT_BRIDGE_URL: undefined,
  VOICESTUDIO_ACCOUNT_BRIDGE_TOKEN: undefined,
};

/**
 * Wires VoiceStudio Cloud sign-in. Must run before the backend starts (bridge env).
 * Never throws: an optional feature must not stop the local app from starting.
 */
export async function startAccount(opts: StartOptions): Promise<() => void> {
  try {
    return await wireAccount(opts);
  } catch (error) {
    console.error('[account] disabled for this run:', (error as Error).name);
    return () => {};
  }
}

async function wireAccount(opts: StartOptions): Promise<() => void> {
  const available = cloudAccountsAvailable(app.isPackaged);
  const env = resolveCloudEnvironment({
    packaged: app.isPackaged,
    requested: process.env.VOICESTUDIO_CLOUD_ENV,
  });
  const switches = new CloudSwitchStore(join(app.getPath('userData'), 'cloud-switches.json'));
  const allowed = () => available && switches.get().accountEnabled;
  const activity = new CloudActivity({ isAllowed: allowed, origins: cloudOrigins(env) });
  const store = new RefreshTokenStore(join(app.getPath('userData'), 'account.json'), safeStorage);
  const oidc = new OidcClient(env, activity);
  const session = new AccountSession({
    oidc,
    store,
    activity,
    switches,
    startLoopback,
    openExternal: (url) => shell.openExternal(url),
    signedInPage: env.signedInPage,
  });
  const api = new AccountApi(env, session, activity);
  const ctl = new AccountController({
    available,
    switches,
    session,
    api,
    remembered: store.persistent,
  });
  const closeIpc = registerAccountIpc(ctl, session, opts.getMainWindow);
  if (!available)
    return () => {
      closeIpc();
      activity.stopAll();
    };
  const bridge = await startAccountTokenBridge({
    getToken: () => session.getAccessToken(),
    isSyncAllowed: () => switches.get().syncEnabled,
    isRemoteBackend: opts.isRemoteBackend,
  });
  // Only the managed backend's spawn env carries the capability; see setBackendOnlyEnv.
  setBackendOnlyEnv({
    VOICESTUDIO_ACCOUNT_BRIDGE_URL: bridge.url,
    VOICESTUDIO_ACCOUNT_BRIDGE_TOKEN: bridge.token,
  });
  return () => {
    closeIpc();
    activity.stopAll();
    bridge.close();
    setBackendOnlyEnv(BRIDGE_ENV_OFF);
  };
}
