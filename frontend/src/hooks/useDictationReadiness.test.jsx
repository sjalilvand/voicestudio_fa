import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const { apiJson, installRecommendedAsr } = vi.hoisted(() => ({
  apiJson: vi.fn(),
  installRecommendedAsr: vi.fn(),
}));
vi.mock('../store', () => ({
  useAppStore: Object.assign((selector) => selector({ dictationModelId: 'sherpa-whisper-tiny' }), {
    getState: () => ({ dictationModelId: 'sherpa-whisper-tiny' }),
    setState: vi.fn(),
  }),
}));
vi.mock('../api/client', () => ({ apiJson }));
vi.mock('../utils/asrModelMissing', () => ({ installRecommendedAsr }));
import { useDictationReadiness } from './useDictationReadiness';
const missing = { recommended: { repo_id: 'test/model', label: 'Tiny', size_gb: 0.1 } };
beforeEach(() => {
  vi.resetAllMocks();
});
it('checks without downloading, then waits for explicit installation and rechecks', async () => {
  apiJson.mockResolvedValueOnce({ ready: false, missing }).mockResolvedValue({ ready: true });
  let finish;
  installRecommendedAsr.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const { result } = renderHook(useDictationReadiness);
  expect(result.current.phase).toBe('checking');
  await waitFor(() => expect(result.current.phase).toBe('missing'));
  expect(installRecommendedAsr).not.toHaveBeenCalled();
  let pending;
  act(() => {
    pending = result.current.install();
  });
  expect(result.current.phase).toBe('installing');
  await act(async () => {
    finish();
    await pending;
  });
  expect(result.current.phase).toBe('ready');
  expect(apiJson).toHaveBeenCalledTimes(2);
});
it('keeps failures retryable without claiming a connection error is missing weights', async () => {
  apiJson.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ ready: false, missing });
  installRecommendedAsr.mockRejectedValue(new Error('download failed'));
  const { result } = renderHook(useDictationReadiness);
  await waitFor(() => expect(result.current.phase).toBe('error'));
  expect(result.current.missing).toBeNull();
  await act(async () => {
    await result.current.check();
  });
  await act(async () => {
    await result.current.install();
  });
  expect(result.current.phase).toBe('missing');
  expect(result.current.error).toBe(true);
});
it('refreshes when returning from settings', async () => {
  apiJson.mockResolvedValueOnce({ ready: false, missing }).mockResolvedValue({ ready: true });
  const { result } = renderHook(useDictationReadiness);
  await waitFor(() => expect(result.current.phase).toBe('missing'));
  act(() => window.dispatchEvent(new Event('focus')));
  await waitFor(() => expect(result.current.phase).toBe('ready'));
});
