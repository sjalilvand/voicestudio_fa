/**
 * Re-read a localStorage-backed store when its key changes outside this
 * module: another window, or a value Cloud sync just pulled (synced-storage
 * dispatches a `storage` event after writing it).
 */
export function onStorageKey(key: string, callback: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const listener = (event: StorageEvent) => {
    if (event.key === key) callback();
  };
  window.addEventListener('storage', listener);
  return () => window.removeEventListener('storage', listener);
}
