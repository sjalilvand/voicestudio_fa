import { act, cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';

const mock = vi.hoisted(() => ({ bridge: null as unknown, mac: false }));
vi.mock('@/components/bridge', () => ({ getBridge: () => mock.bridge, isMac: () => mock.mac }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, vars?: Record<string, unknown>) =>
      vars ? `${key} ${JSON.stringify(vars)}` : key,
  }),
}));
vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children, ...props }: { to: string; children: ReactNode }) => (
    <a href={to} {...props}>
      {children}
    </a>
  ),
}));

import { AccountCorner } from './account-corner';

const signedIn = {
  available: true,
  accountEnabled: true,
  syncEnabled: false,
  prompted: true,
  remembered: true,
  signedIn: true,
  signingIn: false,
  notice: null,
  profile: {
    email: 'ana@example.com',
    displayName: 'Ana Lima',
    avatarUrl: null,
    personalOrganizationId: 'Or1',
    organizations: [],
  },
};

async function show(
  state: Record<string, unknown>,
  beside: 'controls' | 'bell' | 'edge' = 'controls',
) {
  mock.bridge = { account: { get: vi.fn(async () => state), onState: vi.fn(() => () => {}) } };
  const view = render(<AccountCorner beside={beside} />);
  await act(async () => {});
  return view;
}
afterEach(() => {
  cleanup();
  mock.bridge = null;
  mock.mac = false;
  document.documentElement.style.removeProperty('--account-badge-space');
});

it('sits in the top-right corner, left of the Windows/Linux window buttons', async () => {
  await show(signedIn);
  const corner = screen.getByRole('link').closest('[data-slot="account-corner"]')!;
  expect(corner.className).toMatch(/fixed/);
  expect(corner.className).toMatch(/top-/);
  expect(corner.className).toMatch(/right-\[148px\]/);
  expect(corner.className).toMatch(/app-no-drag/);
  expect(screen.getByText('Ana Lima')).toBeInTheDocument();
});

it('on macOS it sits left of the notifications bell, or at the edge where there is none', async () => {
  mock.mac = true;
  await show(signedIn, 'bell');
  expect(screen.getByRole('link').closest('[data-slot="account-corner"]')!.className).toMatch(
    /right-\[3\.25rem\]/,
  );
  cleanup();
  await show(signedIn, 'edge');
  expect(screen.getByRole('link').closest('[data-slot="account-corner"]')!.className).toMatch(
    /right-3\.5/,
  );
});

it('reserves title-bar space while shown so page buttons are never covered, and frees it when hidden', async () => {
  const { unmount } = await show(signedIn);
  expect(document.documentElement.style.getPropertyValue('--account-badge-space')).toMatch(/px$/);
  unmount();
  expect(document.documentElement.style.getPropertyValue('--account-badge-space')).toBe('');
  await show({ ...signedIn, accountEnabled: false });
  expect(document.documentElement.style.getPropertyValue('--account-badge-space')).toBe('');
});
