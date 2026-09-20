import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import '@/i18n';
import { IntegrationDetailPage } from './integration-detail-page';
vi.mock('@tanstack/react-router', () => ({
  useParams: () => ({ slug: 'claude-code' }),
  Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}));
vi.mock('@/components/app-shell/workspace-header', () => ({
  WorkspaceHeader: ({ children }: { children: ReactNode }) => <header>{children}</header>,
}));
vi.mock('@/hooks/use-backend-status', () => ({
  useBackendStatus: () => ({ baseUrl: 'http://127.0.0.1:3912' }),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('sonner', () => ({ toast }));
it('copies the shown live configuration only after the user requests it', async () => {
  const copy = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: copy }, configurable: true });
  render(<IntegrationDetailPage />);
  expect(screen.getByText(/Merge this configuration into/)).toHaveTextContent('.mcp.json');
  expect(copy).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
  await waitFor(() => expect(toast.success).toHaveBeenCalled());
  expect(JSON.parse(copy.mock.calls[0][0]).mcpServers.voicestudio.url).toBe(
    'http://127.0.0.1:3912/mcp',
  );
});
