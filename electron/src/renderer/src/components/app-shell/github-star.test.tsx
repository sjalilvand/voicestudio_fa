import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

vi.mock('@/components/bridge', () => ({ getBridge: () => null }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import { GithubStar } from './github-star';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it('shows a bundled count without contacting GitHub on mount or a timer', async () => {
  const fetchCount = vi.fn();
  vi.stubGlobal('fetch', fetchCount);
  vi.useFakeTimers();
  render(<GithubStar />);
  expect(screen.getByText('43.6K')).toBeVisible();
  await act(async () => { await vi.advanceTimersByTimeAsync(40 * 60 * 1000); });
  expect(fetchCount).not.toHaveBeenCalled();
  expect(screen.getByRole('link', { name: 'support.star_github' })).toHaveAttribute(
    'href', 'https://github.com/debpalash/VoiceStudio',
  );
});
