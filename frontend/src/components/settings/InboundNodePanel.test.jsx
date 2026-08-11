import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}));

const { askConfirm } = vi.hoisted(() => ({ askConfirm: vi.fn() }));
vi.mock('../../utils/dialog', () => ({ askConfirm }));

import toast from 'react-hot-toast';
import InboundNodePanel from './InboundNodePanel';

const BASE = {
  enabled: true,
  running: true,
  bind: '127.0.0.1',
  port: 7444,
  exposed: false,
  startup_error: null,
  keys: [],
  sessions: [],
  events: [],
  connections: [],
};

function renderPanel(request) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InboundNodePanel request={request} />
    </QueryClientProvider>,
  );
}

/** A `request` stub in the shape WorkersPanel passes down. */
const stub = (state) =>
  vi.fn(async (path) => {
    if (path === '/workers/inbound') return state;
    return state;
  });

beforeEach(() => {
  vi.clearAllMocks();
});

describe('InboundNodePanel', () => {
  it('says the GPU is only reachable locally until the bind is widened', async () => {
    renderPanel(stub(BASE));

    expect(await screen.findByText(/Only this machine can reach it/i)).toBeTruthy();
    expect(screen.queryByText(/On your network/i)).toBeNull();
  });

  it('warns that a widened bind exposes an unencrypted credential', async () => {
    // The whole security posture of this mode rests on the user knowing this
    // at the moment it becomes true, so a silent badge is not enough — the
    // address and the reason both have to be on screen.
    renderPanel(stub({ ...BASE, bind: '0.0.0.0', exposed: true }));

    expect(await screen.findByText(/not encrypted/i)).toBeTruthy();
    expect(screen.getByText(/0\.0\.0\.0:7444/)).toBeTruthy();
    // Exact match: the same words appear inside the warning sentence, and a
    // substring query would pass even if the badge itself disappeared.
    expect(screen.getByText('On your network')).toBeTruthy();
  });

  it('shows a new connection string once, with the warning attached', async () => {
    const request = vi.fn(async (path) => {
      if (path === '/workers/inbound/keys') {
        return {
          key_id: 'abc',
          label: 'Alice',
          connection_string: 'ovnode://ovnode_secret@10.0.0.2:7444',
        };
      }
      return BASE;
    });
    renderPanel(request);

    fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'Alice' } });
    fireEvent.click(screen.getByText('Create'));

    expect(await screen.findByText('ovnode://ovnode_secret@10.0.0.2:7444')).toBeTruthy();
    expect(screen.getByText(/not shown again/i)).toBeTruthy();
    expect(screen.getByText(/like a password/i)).toBeTruthy();
  });

  it('says removing one person leaves everyone else connected', async () => {
    // The confirm text is the only place the user learns that keys are per
    // person; if it read like a global switch they would avoid using it.
    askConfirm.mockResolvedValue(false);
    renderPanel(
      stub({
        ...BASE,
        keys: [{ key_id: 'k1', label: 'Alice', revoked: false, last_seen_at: 0 }],
      }),
    );

    fireEvent.click(await screen.findByText('Remove'));

    await waitFor(() => expect(askConfirm).toHaveBeenCalled());
    expect(askConfirm.mock.calls[0][0]).toMatch(/Everyone else stays connected/i);
  });

  it('lists who is connected and can disconnect them', async () => {
    const request = stub({
      ...BASE,
      sessions: [
        {
          session_id: 's1',
          label: 'Bob',
          peer: '10.0.0.9:5000',
          tasks_run: 3,
          connected_at: 0,
        },
      ],
    });
    renderPanel(request);

    expect(await screen.findByText(/Bob/)).toBeTruthy();
    expect(screen.getByText(/10\.0\.0\.9:5000/)).toBeTruthy();

    fireEvent.click(screen.getByText('Disconnect'));

    await waitFor(() =>
      expect(request).toHaveBeenCalledWith(
        '/workers/inbound/sessions/s1/disconnect',
        expect.objectContaining({ method: 'POST' }),
      ),
    );
  });

  it('surfaces the parser message when a pasted string is wrong', async () => {
    // Every bad paste otherwise reads as "cannot connect", which is what a
    // firewall, a wrong port and a dead node all say too.
    const request = vi.fn(async (path) => {
      if (path === '/workers/inbound/connections') {
        throw new Error('That looks like an address without a key.');
      }
      return BASE;
    });
    renderPanel(request);

    fireEvent.change(await screen.findByLabelText('Connection string'), {
      target: { value: '192.168.0.110:7444' },
    });
    fireEvent.click(screen.getByText('Connect'));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('That looks like an address without a key.'),
    );
  });

  it('hides the sharing controls entirely while the feature is off', async () => {
    renderPanel(stub({ ...BASE, enabled: false, running: false }));

    expect(await screen.findByText('Accept connections')).toBeTruthy();
    expect(screen.queryByText('Add a person')).toBeNull();
    expect(screen.queryByText('Connected right now')).toBeNull();
  });
});
