import { act, cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';

const mock = vi.hoisted(() => ({ bridge: null as unknown }));
vi.mock('@/components/bridge', () => ({ getBridge: () => mock.bridge }));
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

import { AccountBadge } from './account-badge';

const signedIn = {
  available: true,
  accountEnabled: true,
  syncEnabled: false,
  prompted: true,
  remembered: true,
  signedIn: true,
  signingIn: false,
  notice: null as string | null,
  profile: {
    email: 'ana@example.com',
    displayName: 'Ana Lima' as string | null,
    avatarUrl: null as string | null,
    personalOrganizationId: 'Or1',
    organizations: [],
  },
};

async function show(state: Record<string, unknown>, compact = false) {
  mock.bridge = {
    account: { get: vi.fn(async () => state), onState: vi.fn(() => () => {}) },
  };
  const view = render(<AccountBadge compact={compact} />);
  await act(async () => {});
  return view;
}
afterEach(() => {
  cleanup();
  mock.bridge = null;
});

it('shows the signed-in name with initials when there is no photo, linking to Settings → Account', async () => {
  await show(signedIn);
  const link = screen.getByRole('link');
  expect(link).toHaveAttribute('href', '/settings/account');
  expect(link).toHaveAccessibleName(/account\.signed_in_as.*Ana Lima/);
  expect(screen.getByText('Ana Lima')).toBeInTheDocument();
  expect(screen.getByText('AL')).toBeInTheDocument();
});

it('shows the profile photo when one was uploaded', async () => {
  await show({
    ...signedIn,
    profile: { ...signedIn.profile, avatarUrl: 'data:image/png;base64,AAAA' },
  });
  expect(document.querySelector('img')).toHaveAttribute('src', 'data:image/png;base64,AAAA');
  expect(screen.queryByText('AL')).toBeNull();
});

it('falls back to the email when there is no display name', async () => {
  await show({ ...signedIn, profile: { ...signedIn.profile, displayName: null } });
  expect(screen.getByText('ana@example.com')).toBeInTheDocument();
  expect(screen.getByText('A')).toBeInTheDocument();
});

it('compact: just the avatar, with the name as its label', async () => {
  await show(signedIn, true);
  expect(screen.queryByText('Ana Lima')).toBeNull();
  expect(screen.getByRole('link')).toHaveAccessibleName(/Ana Lima/);
});

it('an expired session asks to sign in again', async () => {
  await show({ ...signedIn, signedIn: false, notice: 'signed_out_expired', profile: null });
  expect(screen.getByRole('link')).toHaveTextContent('account.badge_sign_in_again');
});

it.each([
  ['account features off', { ...signedIn, accountEnabled: false }],
  ['the build has no accounts', { ...signedIn, available: false }],
  ['signed out', { ...signedIn, signedIn: false, profile: null }],
])('shows nothing when %s', async (_name, state) => {
  const { container } = await show(state);
  expect(container).toBeEmptyDOMElement();
});

it('shows nothing in the browser build (no bridge)', async () => {
  const { container } = render(<AccountBadge />);
  expect(container).toBeEmptyDOMElement();
});
