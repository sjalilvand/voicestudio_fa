import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('@/components/bridge', () => ({ isMac: () => true }));
vi.mock('./support-shortcut', () => ({ SupportShortcut: () => null }));

import { WorkspaceHeader } from './workspace-header';

afterEach(cleanup);

it('renders page actions with the shared header controls', () => {
  const openHistory = vi.fn();

  render(
    <WorkspaceHeader actions={<button onClick={openHistory}>History</button>}>
      <h1>Voice Design</h1>
    </WorkspaceHeader>,
  );

  fireEvent.click(screen.getByRole('button', { name: 'History' }));
  expect(openHistory).toHaveBeenCalledOnce();
});
