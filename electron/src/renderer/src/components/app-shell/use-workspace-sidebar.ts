import { useSyncExternalStore } from 'react';
import { useRouterState } from '@tanstack/react-router';
import { setWorkspace, useWorkspace } from '@/lib/store/workspace';

const SECONDARY_ROUTES = new Set([
  '/stories',
  '/audiobook',
  '/tools',
  '/batch',
  '/gallery',
  '/personas',
  '/projects',
  '/dub',
  '/design',
  '/transcriptions',
  '/calls',
  // CLEAN-ROOM (spec N-jaketame-2 §9): the Settings route belongs in this set.
]);
// Voice-section routes whose context pane is the shared library (ContextSidebar).
export const LIBRARY_ROUTES = new Set(['/', '/clone']);
// Rail + context panel, as in VS Code, Slack and Linear: a section that brings its
// own pane keeps navigation to an icon rail so the window never shows two wide
// sidebars. The full navigation stays one click (or the Keep-expanded
// preference) away. A genuinely narrow window always uses the rail.
// Browser zoom and Windows display scaling are included in the CSS viewport
// width, so this threshold also covers high-DPI layouts.
const COMPACT_QUERY = '(max-width: 1200px)';

function normalize(pathname: string): string {
  return pathname.replace(/\/+$/, '') || '/';
}

function routeHasSecondarySidebar(pathname: string): boolean {
  const normalized = normalize(pathname);
  return (
    LIBRARY_ROUTES.has(normalized) ||
    [...SECONDARY_ROUTES].some((route) => normalized === route || normalized.startsWith(`${route}/`))
  );
}

function useCompactViewport(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia(COMPACT_QUERY);
      query.addEventListener('change', notify);
      return () => query.removeEventListener('change', notify);
    },
    () => window.matchMedia(COMPACT_QUERY).matches,
    () => false,
  );
}

export function useWorkspaceSidebarState() {
  // CLEAN-ROOM (spec N-jaketame-2 §9): read libraryOpen, expandedLibraryContext and the auto-collapse preference from the workspace store.
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const compactViewport = useCompactViewport();
  const compactContext = `${pathname}:${compactViewport}`;
  const forceExpanded = expandedLibraryContext === compactContext;
  // CLEAN-ROOM (spec N-jaketame-2 §9): `autoCollapse` flag combining the preference, section-pane routes and a narrow viewport.
  const compact = !libraryOpen || (autoCollapse && !forceExpanded);
  const setOpen = (open: boolean) =>
    setWorkspace({ libraryOpen: open, expandedLibraryContext: open ? compactContext : null });
  return {
    compact,
    compactViewport,
    forceExpanded,
    secondaryWorkspace: routeHasSecondarySidebar(pathname),
    setOpen,
  };
}
