import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';

vi.mock('@/components/bridge', () => ({ getBridge: () => null }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import { GithubStar } from './github-star';

const REFRESH_MS = 20 * 60 * 1000;

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <GithubStar />
    </QueryClientProvider>,
  );
  return client;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it('gets the small public count and refreshes once every 20 minutes', async () => {
  const fetchCount = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ count: 43_638 }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ count: 43_755 }) });
  vi.stubGlobal('fetch', fetchCount);
  vi.useFakeTimers();
  const client = mount();

  expect(screen.getByText('43.6K')).toBeVisible();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(fetchCount).toHaveBeenCalledOnce();
  expect(fetchCount.mock.calls[0][0]).toBe(
    'https://api.github.com/repos/debpalash/VoiceStudio/stargazers/count',
  );
  expect(fetchCount.mock.calls[0][1]).toMatchObject({
    credentials: 'omit',
    referrerPolicy: 'no-referrer',
  });

  await act(async () => {
    await vi.advanceTimersByTimeAsync(REFRESH_MS - 1);
  });
  expect(fetchCount).toHaveBeenCalledOnce();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(fetchCount).toHaveBeenCalledTimes(2);
  expect(client.getQueryData(['github-star-count'])).toBe(43_755);
  vi.useRealTimers();
  await waitFor(() => expect(screen.getByText('43.8K')).toBeVisible());
  client.clear();
});

it('keeps the bundled count when GitHub is unreachable', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
  vi.useFakeTimers();
  const client = mount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(screen.getByText('43.6K')).toBeVisible();
  client.clear();
});

it('keeps the last live count if a later refresh fails', async () => {
  const fetchCount = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ count: 45_000 }) })
    .mockRejectedValueOnce(new Error('offline'));
  vi.stubGlobal('fetch', fetchCount);
  vi.useFakeTimers();
  const client = mount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(screen.getByText('45K')).toBeVisible();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(REFRESH_MS + 1);
  });
  expect(fetchCount).toHaveBeenCalledTimes(2);
  expect(screen.getByText('45K')).toBeVisible();
  client.clear();
});
