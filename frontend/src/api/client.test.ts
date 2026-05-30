import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('apiFetch PIN header', () => {
  let realFetch: typeof globalThis.fetch;
  beforeEach(() => { realFetch = globalThis.fetch; sessionStorage.clear(); });
  afterEach(() => { globalThis.fetch = realFetch; sessionStorage.clear(); });

  it('attaches X-OmniVoice-Pin when present in sessionStorage', async () => {
    sessionStorage.setItem('ov_pin', '424242');
    const seen: any = {};
    globalThis.fetch = vi.fn((_url, opts) => { Object.assign(seen, opts); return Promise.resolve({ ok: true, json: async () => ({}) }); }) as any;
    const { apiFetch } = await import('./client');
    await apiFetch('/system/info');
    expect((seen.headers || {})['X-OmniVoice-Pin']).toBe('424242');
  });

  it('omits the header when no pin', async () => {
    const seen: any = {};
    globalThis.fetch = vi.fn((_url, opts) => { Object.assign(seen, opts); return Promise.resolve({ ok: true, json: async () => ({}) }); }) as any;
    const { apiFetch } = await import('./client');
    await apiFetch('/system/info');
    expect((seen.headers || {})['X-OmniVoice-Pin']).toBeUndefined();
  });
});
