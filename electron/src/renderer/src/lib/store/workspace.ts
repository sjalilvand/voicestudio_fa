import { useSyncExternalStore } from 'react';
type Layout = {
  expandedLibraryContext?: string | null;
  editingProfileId?: string | null;
  panel: 'voice' | null;
  libraryOpen: boolean;
  libraryTab: 'voices' | 'takes';
  // CLEAN-ROOM (spec N-jaketame-2 §8): persisted boolean preference field for auto-collapsing the sidebar.
};
const key = 'voicestudio.workspace-layout';
// CLEAN-ROOM (spec N-jaketame-2 §8): `defaults` layout constant (panel null, library open, voices tab, auto-collapse on).
function read(): Layout {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? '{}');
    return {
      // Voice controls moved to a composer popover; a stored 'settings' pane is dropped.
      panel: value?.panel === 'voice' ? 'voice' : null,
      libraryOpen: typeof value?.libraryOpen === 'boolean' ? value.libraryOpen : true,
      libraryTab: value?.libraryTab === 'takes' ? 'takes' : 'voices',
      // CLEAN-ROOM (spec N-jaketame-2 §8): read the stored auto-collapse preference, default true.
    };
  } catch {
    return defaults;
  }
}
let current = read();
const listeners = new Set<() => void>();
export function setWorkspace(patch: Partial<Layout>) {
  current = { ...current, ...patch };
  try {
    localStorage.setItem(key, JSON.stringify(current));
  } catch {
    /* Session layout remains available. */
  }
  listeners.forEach((listener) => listener());
}
export function useWorkspace() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => current,
  );
}
