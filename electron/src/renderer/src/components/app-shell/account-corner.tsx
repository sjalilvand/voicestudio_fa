import { useLayoutEffect, useRef } from 'react';
import { isMac } from '@/components/bridge';
import { cn } from '@/lib/utils';
import { AccountBadge } from './account-badge';

const SPACE_VAR = '--account-badge-space';

/**
 * The signed-in badge in the window's top-right corner, on every page.
 *
 * Windows/Linux draw their window buttons over the right 148px (titleBarOverlay),
 * macOS has the notifications bell there; the badge sits just left of them.
 * While it shows, `--account-badge-space` widens every page title bar's
 * right padding (globals.css) so it never covers a page's own buttons.
 */
const RIGHT = {
  controls: 'right-[148px]', // Windows/Linux: left of the window buttons
  bell: 'right-[3.25rem]', // macOS workspaces: left of the notifications bell
  edge: 'right-3.5', // macOS Settings: nothing else in the corner
} as const;

export function AccountCorner({ beside }: { beside?: keyof typeof RIGHT }) {
  const host = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const root = document.documentElement;
    const node = host.current;
    const measure = () => {
      const badge = node?.firstElementChild as HTMLElement | null;
      if (badge) root.style.setProperty(SPACE_VAR, `${Math.ceil(badge.offsetWidth) + 8}px`);
      else root.style.removeProperty(SPACE_VAR);
    };
    measure();
    const observer =
      node && typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    if (node && observer) observer.observe(node);
    const mutations =
      node && typeof MutationObserver !== 'undefined' ? new MutationObserver(measure) : null;
    if (node && mutations) mutations.observe(node, { childList: true });
    return () => {
      observer?.disconnect();
      mutations?.disconnect();
      root.style.removeProperty(SPACE_VAR);
    };
  }, []);
  return (
    <div
      ref={host}
      data-slot="account-corner"
      className={cn(
        'app-no-drag fixed top-2.5 z-50 flex items-center',
        RIGHT[beside ?? (isMac() ? 'bell' : 'controls')],
      )}
    >
      <AccountBadge className="h-8 rounded-full border border-border/60 bg-background/80 py-1 pr-3 pl-1 shadow-xs backdrop-blur-xl" />
    </div>
  );
}
