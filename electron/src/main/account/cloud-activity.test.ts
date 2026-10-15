import { expect, it, vi } from 'vitest';
import { CloudActivity, CloudDisabledError, type FetchImpl } from './cloud-activity';

const origins = new Set(['https://voicestudio.sh']);

it('refuses every request while switched off, without touching the network', async () => {
  const fetchImpl = vi.fn();
  const activity = new CloudActivity({ isAllowed: () => false, origins, fetchImpl });
  await expect(activity.fetch('https://voicestudio.sh/x')).rejects.toBeInstanceOf(
    CloudDisabledError,
  );
  expect(fetchImpl).not.toHaveBeenCalled();
});

it('refuses origins outside the configured environment', async () => {
  const fetchImpl = vi.fn();
  const activity = new CloudActivity({ isAllowed: () => true, origins, fetchImpl });
  await expect(activity.fetch('https://evil.example/x')).rejects.toThrow(/origin/);
  expect(fetchImpl).not.toHaveBeenCalled();
});

it('stopAll aborts in-flight requests, cancels timers and runs stop hooks', async () => {
  let seen: AbortSignal | undefined;
  const fetchImpl = vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        seen = init!.signal!;
        seen.addEventListener('abort', () => reject(seen!.reason));
      }),
  );
  const activity = new CloudActivity({ isAllowed: () => true, origins, fetchImpl });
  const timer = vi.fn();
  const hook = vi.fn();
  vi.useFakeTimers();
  activity.setTimeout(timer, 1000);
  activity.onStop(hook);
  const pending = activity.fetch('https://voicestudio.sh/x');
  activity.stopAll();
  await expect(pending).rejects.toBeTruthy();
  vi.advanceTimersByTime(5000);
  vi.useRealTimers();
  expect(seen?.aborted).toBe(true);
  expect(timer).not.toHaveBeenCalled();
  expect(hook).toHaveBeenCalledOnce();
});

it('allows exactly one final call after stopAll (the revocation)', async () => {
  const fetchImpl = vi.fn(async () => new Response('{}'));
  let allowed = true;
  const activity = new CloudActivity({ isAllowed: () => allowed, origins, fetchImpl });
  allowed = false;
  activity.stopAll();
  await activity.fetch('https://voicestudio.sh/revoke', {}, { final: true });
  await expect(
    activity.fetch('https://voicestudio.sh/revoke', {}, { final: true }),
  ).rejects.toBeInstanceOf(CloudDisabledError);
  expect(fetchImpl).toHaveBeenCalledOnce();
});

it('never follows redirects', async () => {
  const fetchImpl = vi.fn<FetchImpl>(async () => new Response('{}'));
  const activity = new CloudActivity({ isAllowed: () => true, origins, fetchImpl });
  await activity.fetch('https://voicestudio.sh/x');
  expect(fetchImpl.mock.calls[0][1]).toMatchObject({ redirect: 'error' });
});
