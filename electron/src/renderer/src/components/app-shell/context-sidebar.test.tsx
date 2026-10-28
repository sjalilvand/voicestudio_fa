import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

const route = vi.hoisted(() => ({ pathname: '/clone' }));
const workspace = vi.hoisted(() => ({ libraryOpen: false, libraryTab: 'voices' as const }));
// CLEAN-ROOM (spec W11-residue §T32): hoisted setWorkspace mock and router/i18n/workspace-store mocks
vi.mock('@/features/clone/voices-sidebar', () => ({
  VoicesSidebar: () => <div>Voice library</div>,
}));

import { ContextSidebar } from './context-sidebar';

beforeEach(() => {
  workspace.libraryOpen = false;
  workspace.libraryTab = 'voices';
  setWorkspace.mockClear();
});

it('reopens a collapsed library pane when a library shortcut opens it', () => {
  const view = render(<ContextSidebar />);
  expect(document.querySelector('[data-slot="secondary-sidebar"]')).toHaveAttribute(
    'data-collapsed',
    'true',
  );

  workspace.libraryOpen = true;
  view.rerender(<ContextSidebar />);
  expect(document.querySelector('[data-slot="secondary-sidebar"]')).not.toHaveAttribute(
    'data-collapsed',
  );
  expect(screen.getByText('Voice library')).toBeVisible();

  fireEvent.click(screen.getByRole('button', { name: 'paneActions.collapse' }));
  expect(setWorkspace).toHaveBeenCalledWith({ libraryOpen: false });
});
