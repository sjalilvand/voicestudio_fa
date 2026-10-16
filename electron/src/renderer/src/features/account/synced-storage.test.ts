import { afterEach, expect, it, vi } from 'vitest';
import { installSyncedStorage } from './synced-storage';

const KEYS = ['voicestudio.theme.v2', 'voicestudio.clone.settings.v1'];
let uninstall: (() => void) | undefined;
afterEach(() => {
  uninstall?.();
  uninstall = undefined;
  localStorage.clear();
});

function install() {
  const post = vi.fn(async (_key: string, _value: unknown, _raw: boolean) => {});
  const synced = installSyncedStorage({ storage: localStorage, keys: KEYS, post });
  uninstall = synced.uninstall;
  return { post, synced };
}

it('posts each change to a synced key once, parsed when it is JSON', () => {
  const { post } = install();
  localStorage.setItem('voicestudio.clone.settings.v1', JSON.stringify({ steps: 16 }));
  localStorage.setItem('voicestudio.theme.v2', 'dark');
  localStorage.removeItem('voicestudio.theme.v2');
  expect(post.mock.calls).toEqual([
    ['voicestudio.clone.settings.v1', { steps: 16 }, false],
    ['voicestudio.theme.v2', 'dark', true],
    ['voicestudio.theme.v2', null, false],
  ]);
});

it('ignores keys that never sync and still stores them', () => {
  const { post } = install();
  localStorage.setItem('voicestudio.workspace-layout', 'x');
  expect(post).not.toHaveBeenCalled();
  expect(localStorage.getItem('voicestudio.workspace-layout')).toBe('x');
});

it('applies a pulled value without echoing it and tells the app through a storage event', () => {
  const { post, synced } = install();
  const seen: (string | null)[] = [];
  const listener = (event: StorageEvent) => seen.push(event.key);
  window.addEventListener('storage', listener);
  synced.apply('voicestudio.theme.v2', 'light', true);
  synced.apply('voicestudio.clone.settings.v1', { steps: 24 }, false);
  synced.apply('voicestudio.theme.v2', null, true);
  window.removeEventListener('storage', listener);
  expect(post).not.toHaveBeenCalled();
  expect(localStorage.getItem('voicestudio.clone.settings.v1')).toBe('{"steps":24}');
  expect(localStorage.getItem('voicestudio.theme.v2')).toBeNull();
  expect(seen).toEqual([
    'voicestudio.theme.v2',
    'voicestudio.clone.settings.v1',
    'voicestudio.theme.v2',
  ]);
});

it('reads the current values of every synced key for the first mirror', () => {
  localStorage.setItem('voicestudio.theme.v2', 'dark');
  const { synced } = install();
  expect(synced.snapshot()).toEqual([['voicestudio.theme.v2', 'dark', true]]);
});

it('uninstall restores the original storage methods', () => {
  const original = Storage.prototype.setItem;
  const { post } = install();
  uninstall!();
  uninstall = undefined;
  expect(Storage.prototype.setItem).toBe(original);
  localStorage.setItem('voicestudio.theme.v2', 'dark');
  expect(post).not.toHaveBeenCalled();
});

it('a failing post never breaks the write', () => {
  const post = vi.fn(async () => {
    throw new Error('backend down');
  });
  const synced = installSyncedStorage({ storage: localStorage, keys: KEYS, post });
  uninstall = synced.uninstall;
  expect(() => localStorage.setItem('voicestudio.theme.v2', 'dark')).not.toThrow();
  expect(localStorage.getItem('voicestudio.theme.v2')).toBe('dark');
});
