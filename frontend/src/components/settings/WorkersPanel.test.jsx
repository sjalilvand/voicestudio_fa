import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}));

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('../../api/client', () => ({ apiFetch }));

const { askConfirm } = vi.hoisted(() => ({ askConfirm: vi.fn() }));
vi.mock('../../utils/dialog', () => ({ askConfirm }));

import WorkersPanel, { WorkerRow } from './WorkersPanel';

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WorkersPanel />
    </QueryClientProvider>,
  );
}

const WORKER = {
  id: 'w1',
  name: 'Desktop 4090',
  enabled: true,
  connected: true,
  consent_granted: true,
  active_tasks: 1,
  available_slots: 1,
  breakers: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  askConfirm.mockResolvedValue(true);
});

describe('WorkersPanel', () => {
  it('shows nothing beyond the toggle while the feature is off', async () => {
    apiFetch.mockResolvedValue({ enabled: false, running: false, workers: [] });
    renderPanel();

    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith('/workers'));
    // The endpoint, the token button, and the worker list are all consequences
    // of enabling — an off feature must not advertise its surface.
    expect(screen.queryByText(/Generate token/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Workers connect to/i)).not.toBeInTheDocument();
  });

  it('reveals the endpoint and add flow once enabled', async () => {
    apiFetch.mockResolvedValue({
      enabled: true,
      running: true,
      endpoint: 'my-mac:7443',
      workers: [],
    });
    renderPanel();

    expect(await screen.findByText('my-mac:7443')).toBeInTheDocument();
    expect(screen.getByText(/Generate token/i)).toBeInTheDocument();
    expect(screen.getByText(/No workers yet/i)).toBeInTheDocument();
  });

  it('shows the token once, with its shown-once warning', async () => {
    apiFetch.mockImplementation((path) => {
      if (path === '/workers') {
        return Promise.resolve({ enabled: true, running: true, workers: [] });
      }
      return Promise.resolve({ token: 'ovw_abc123', expires_at: 1 });
    });
    renderPanel();

    fireEvent.click(await screen.findByText(/Generate token/i));

    expect(await screen.findByText('ovw_abc123')).toBeInTheDocument();
    expect(screen.getByText(/shown only once/i)).toBeInTheDocument();
  });

  it('confirms before removing, because removal revokes the key', async () => {
    apiFetch.mockResolvedValue({
      enabled: true,
      running: true,
      workers: [WORKER],
    });
    renderPanel();

    fireEvent.click(await screen.findByText(/Remove/i));

    await waitFor(() => expect(askConfirm).toHaveBeenCalled());
    expect(askConfirm.mock.calls[0][0]).toMatch(/revoked/i);
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith('/workers/w1', { method: 'DELETE' }),
    );
  });

  it('does not remove when the confirmation is declined', async () => {
    askConfirm.mockResolvedValue(false);
    apiFetch.mockResolvedValue({ enabled: true, running: true, workers: [WORKER] });
    renderPanel();

    fireEvent.click(await screen.findByText(/Remove/i));

    await waitFor(() => expect(askConfirm).toHaveBeenCalled());
    expect(apiFetch).not.toHaveBeenCalledWith('/workers/w1', { method: 'DELETE' });
  });
});

describe('WorkerRow', () => {
  const noop = () => {};

  it('reports an online worker and its load', () => {
    render(<WorkerRow worker={WORKER} onRemove={noop} onResume={noop} onToggle={noop} />);
    expect(screen.getByText('Online')).toBeInTheDocument();
    expect(screen.getByText(/Tasks 1 \/ 2/)).toBeInTheDocument();
  });

  it('surfaces the breaker reason instead of a bare percentage', () => {
    render(
      <WorkerRow
        worker={{
          ...WORKER,
          breakers: [{ summary: 'Paused after 3 failures (boom) — retrying in 45s' }],
        }}
        onRemove={noop}
        onResume={noop}
        onToggle={noop}
      />,
    );
    expect(screen.getByText('Paused')).toBeInTheDocument();
    expect(screen.getByText(/retrying in 45s/)).toBeInTheDocument();
    expect(screen.getByText(/Resume/)).toBeInTheDocument();
  });

  it('flags a worker that has not been approved', () => {
    render(
      <WorkerRow
        worker={{ ...WORKER, consent_granted: false }}
        onRemove={noop}
        onResume={noop}
        onToggle={noop}
      />,
    );
    expect(screen.getByText('Not approved')).toBeInTheDocument();
  });

  it('shows a disabled worker as disabled rather than offline', () => {
    render(
      <WorkerRow
        worker={{ ...WORKER, enabled: false }}
        onRemove={noop}
        onResume={noop}
        onToggle={noop}
      />,
    );
    expect(screen.getByText('Disabled')).toBeInTheDocument();
  });
});
