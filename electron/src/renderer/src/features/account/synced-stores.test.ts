import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { useReviewMode } from '@/hooks/use-review-mode';
import { useAppearance } from '@/hooks/use-appearance';
import { cloneSettingsStore } from '@/lib/store/clone-settings';

/** A pulled value arrives: synced-storage writes localStorage and fires a storage event. */
function pull(key: string, stored: string) {
  localStorage.setItem(key, stored);
  window.dispatchEvent(new StorageEvent('storage', { key, newValue: stored }));
}

afterEach(() => localStorage.clear());

it('review mode follows a pulled value', () => {
  const { result } = renderHook(() => useReviewMode());
  act(() => pull('voicestudio.review-mode.v1', 'off'));
  expect(result.current).toBe('off');
  act(() => pull('voicestudio.review-mode.v1', 'on'));
  expect(result.current).toBe('on');
});

it('appearance follows a pulled value', () => {
  const { result } = renderHook(() => useAppearance());
  act(() =>
    pull('voicestudio.appearance', JSON.stringify({ font: 'system', scale: 110, glass: false })),
  );
  expect(result.current).toMatchObject({ font: 'system', scale: 110, glass: false });
});

it('generation defaults follow a pulled value instead of writing the old ones back', () => {
  const before = cloneSettingsStore.state;
  act(() =>
    pull(
      'voicestudio.clone.settings.v1',
      JSON.stringify({ ...before, steps: before.steps === 24 ? 16 : 24 }),
    ),
  );
  expect(cloneSettingsStore.state.steps).toBe(before.steps === 24 ? 16 : 24);
});
