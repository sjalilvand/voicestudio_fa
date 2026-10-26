import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { FilmIcon } from 'lucide-react';
import { MAC_TRAFFIC_LIGHTS_INLINE_END } from '@shared/utils/windowChrome';
import { SecondarySidebar } from './workspace-sidebar';

const platform = vi.hoisted(() => ({ mac: false }));
vi.mock('@/components/bridge', () => ({ isMac: () => platform.mac }));
vi.mock('@/hooks/use-window-fullscreen', () => ({ useWindowFullscreen: () => false }));

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// CLEAN-ROOM (spec N-jaketame-2 §13): tests for the secondary sidebar (resizable width persistence,
// pinned footer and collapse reporting, controls/library tabs, header inset beside macOS traffic lights).

it('collapses to one expand control, leaving the titlebar row empty', () => {
  render(
    <SecondarySidebar title="Voice" icon={FilmIcon} collapsed onCollapsedChange={vi.fn()}>
      <section>Body</section>
    </SecondarySidebar>,
  );
  const header = document.querySelector<HTMLElement>('[data-slot="secondary-sidebar-header"]')!;
  expect(header.querySelector('button')).toBeNull();
  expect(screen.getAllByRole('button', { expanded: false })).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Voice' })).toHaveAttribute('aria-expanded', 'false');
});
