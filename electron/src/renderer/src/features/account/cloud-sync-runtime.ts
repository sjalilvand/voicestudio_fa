import { useEffect } from 'react';
import { apiJson } from '@/lib/api/client';
import { getBridge } from '@/components/bridge';
import { installSyncedStorage } from './synced-storage';
import { useAccount } from './use-account';

/** Virtual key: the dictation shortcut lives in main, reached through the capture bridge. */
const SHORTCUT_KEY = 'voicestudio.shortcut.dictation';

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
interface Capture {
  getShortcut(): Promise<{ accelerator: string; active: boolean; error?: string }>;
  setShortcut(
    accelerator: string,
  ): Promise<{ accelerator: string; active: boolean; error?: string }>;
}

/**
 * While the user is signed in with sync on: mirror synced localStorage keys to
 * the backend, apply what the backend pulled, and nudge a round on focus.
 */
export async function startCloudSyncRuntime(deps: {
  api: Api;
  capture?: Capture;
  intervalMs?: number;
}): Promise<() => void> {
  const { api, capture } = deps;
  const { keys } = await api<{ keys: string[] }>('/api/cloud-sync/local/keys');
  const post = (key: string, value: unknown, raw: boolean) =>
    api('/api/cloud-sync/local', { method: 'PUT', body: JSON.stringify({ key, value, raw }) }).then(
      () => {},
    );
  const synced = installSyncedStorage({
    storage: localStorage,
    keys: keys.filter((key) => key !== SHORTCUT_KEY),
    post,
  });
  let stopped = false;
  let seq = 0;
  let shortcut: string | null = null;
  // The accelerator still active after this OS refused a synced one: not a user change.
  let refusedFallback: string | null = null;

  const readShortcut = async () => {
    if (!capture || !keys.includes(SHORTCUT_KEY)) return;
    const current = (await capture.getShortcut().catch(() => null))?.accelerator ?? null;
    if (current && current !== shortcut) {
      shortcut = current;
      await post(SHORTCUT_KEY, current, true).catch(() => {});
    }
  };

  for (const [key, value, raw] of synced.snapshot()) await post(key, value, raw).catch(() => {});
  await readShortcut();

  const tick = async () => {
    if (stopped) return;
    const pulled = await api<{
      seq: number;
      values: Array<{ key: string; value: unknown; raw: boolean }>;
    }>(`/api/cloud-sync/local?since=${seq}`).catch(() => null);
    if (!pulled || stopped) return;
    seq = pulled.seq;
    for (const { key, value, raw } of pulled.values) {
      if (key === SHORTCUT_KEY) {
        if (capture && typeof value === 'string') {
          // Keep the synced value even when this OS refuses it ("Shortcut in use on this device").
          shortcut = value;
          const result = await capture.setShortcut(value).catch(() => null);
          refusedFallback = result && !result.active ? result.accelerator : null;
        }
      } else synced.apply(key, value, raw);
    }
    await readShortcutIfChangedLocally();
  };

  // A refused synced shortcut leaves the old one active: that must not be pushed back.
  const readShortcutIfChangedLocally = async () => {
    if (!capture || !keys.includes(SHORTCUT_KEY)) return;
    const state = await capture.getShortcut().catch(() => null);
    if (
      state?.active &&
      state.accelerator &&
      state.accelerator !== shortcut &&
      state.accelerator !== refusedFallback
    ) {
      shortcut = state.accelerator;
      await post(SHORTCUT_KEY, state.accelerator, true).catch(() => {});
    }
  };

  // Values the backend pulled before this window opened are applied first.
  await tick();
  const timer = setInterval(() => void tick(), deps.intervalMs ?? 3000);
  const onFocus = () => void api('/api/cloud-sync/run', { method: 'POST' }).catch(() => {});
  window.addEventListener('focus', onFocus);
  return () => {
    stopped = true;
    clearInterval(timer);
    window.removeEventListener('focus', onFocus);
    synced.uninstall();
  };
}

/** Mounted once in the app shell; does nothing unless signed in with sync on. */
export function CloudSyncRuntime() {
  const { state } = useAccount();
  const active = Boolean(
    state?.available && state.signedIn && state.accountEnabled && state.syncEnabled,
  );
  useEffect(() => {
    if (!active) return;
    let stop: (() => void) | undefined;
    let cancelled = false;
    void apiJson<{ enabled: boolean }>('/api/cloud-sync/status')
      .then((status) => {
        if (cancelled || !status.enabled) return;
        return startCloudSyncRuntime({ api: apiJson, capture: getBridge()?.capture }).then((s) => {
          if (cancelled) s();
          else stop = s;
        });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      stop?.();
    };
  }, [active]);
  return null;
}
