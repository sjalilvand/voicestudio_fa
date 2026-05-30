import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import SharingPanel from './SharingPanel';

describe('SharingPanel', () => {
  let realFetch;
  beforeEach(() => { realFetch = global.fetch; });
  afterEach(() => { global.fetch = realFetch; });

  it('shows Tailscale "not detected" when CLI absent', async () => {
    global.fetch = vi.fn((url) => {
      if (String(url).includes('tailscale/status')) return Promise.resolve({ ok: true, json: async () => ({ installed: false }) });
      return Promise.resolve({ ok: true, json: async () => ({ enabled: false }) });
    });
    render(<SharingPanel />);
    // Both the explanatory copy and the install button surface the phrase, so
    // assert at least one node renders rather than requiring a unique match.
    await waitFor(() => expect(screen.getAllByText(/not detected|install tailscale/i).length).toBeGreaterThan(0));
  });
});
