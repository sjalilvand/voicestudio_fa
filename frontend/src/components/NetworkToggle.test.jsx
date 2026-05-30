// frontend/src/components/NetworkToggle.test.jsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import NetworkToggle from './NetworkToggle';

describe('NetworkToggle', () => {
  let realFetch;
  beforeEach(() => { realFetch = global.fetch; });
  afterEach(() => { global.fetch = realFetch; });

  it('defaults to Local when state reports disabled', async () => {
    global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: async () => ({ enabled: false }) }));
    render(<NetworkToggle />);
    await waitFor(() => expect(screen.getByText(/local/i)).toBeInTheDocument());
  });
});
