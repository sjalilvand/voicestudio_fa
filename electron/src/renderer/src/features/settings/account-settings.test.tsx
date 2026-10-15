import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const mock = vi.hoisted(() => ({ bridge: null as unknown }));
vi.mock('@/components/bridge', () => ({ getBridge: () => mock.bridge }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import { AccountSettings } from './account-settings';

const base = {
  available: true, accountEnabled: true, syncEnabled: false, prompted: true, remembered: true,
  signedIn: false, signingIn: false, notice: null as string | null, profile: null as unknown,
};
function setup(state: Partial<typeof base>) {
  let push: (s: unknown) => void = () => {};
  const account = {
    get: vi.fn(async () => ({ ...base, ...state })),
    onState: vi.fn((cb: (s: unknown) => void) => ((push = cb), () => {})),
    setSwitches: vi.fn(async (p: object) => ({ ...base, ...state, ...p })),
    signIn: vi.fn(async () => {}), cancelSignIn: vi.fn(async () => {}), signOut: vi.fn(async () => {}),
  };
  mock.bridge = { account };
  render(<AccountSettings />);
  return { account, push: (s: Partial<typeof base>) => act(() => push({ ...base, ...s })) };
}
afterEach(() => { cleanup(); mock.bridge = null; });

it('turning account features off applies at once, with no confirm step', async () => {
  const { account } = setup({});
  fireEvent.click(await screen.findByRole('switch', { name: 'account.features' }));
  expect(account.setSwitches).toHaveBeenCalledWith({ accountEnabled: false });
});

it('the sync switch is disabled until signed in', async () => {
  setup({});
  expect(await screen.findByRole('switch', { name: 'account.sync' })).toHaveAttribute('aria-disabled', 'true');
});

it('signing in shows the browser hint with a working Cancel', async () => {
  const { account, push } = setup({});
  fireEvent.click(await screen.findByText('account.sign_in'));
  expect(account.signIn).toHaveBeenCalled();
  push({ signingIn: true });
  expect(screen.getByText('account.continue_in_browser')).toBeInTheDocument();
  fireEvent.click(screen.getByText('account.cancel'));
  expect(account.cancelSignIn).toHaveBeenCalled();
});

it.each(['signed_out_expired', 'sign_in_failed', 'offline'])('shows the %s notice', async (notice) => {
  setup({ notice });
  expect(await screen.findByText(`account.${notice}`)).toBeInTheDocument();
});

it('explains a session that will not survive a restart', async () => {
  setup({ remembered: false });
  expect(await screen.findByText('account.not_remembered')).toBeInTheDocument();
});

it('signed in: shows the name and Sign out, and never any token-like text', async () => {
  const { account } = setup({
    signedIn: true,
    profile: { email: 'ana@example.com', displayName: 'Ana', avatarUrl: null, organizations: [] },
  });
  fireEvent.click(await screen.findByText('account.sign_out'));
  expect(account.signOut).toHaveBeenCalled();
  expect(document.body.textContent).not.toMatch(/Bearer|eyJ/);
});

it('renders nothing when the build has accounts unavailable', async () => {
  setup({ available: false });
  await act(async () => {});
  expect(screen.queryByRole('switch')).toBeNull();
});
