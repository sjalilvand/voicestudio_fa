import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const mock = vi.hoisted(() => ({
  open: vi.fn().mockResolvedValue(undefined),
  navigate: vi.fn(),
}));

vi.mock('@/components/bridge', () => ({
  getBridge: () => ({ files: { openExternal: mock.open } }),
}));
vi.mock('@tanstack/react-router', () => ({ useNavigate: () => mock.navigate }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { SponsorFooter } from './sponsor-footer';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

it('shows Integrations, Become a Sponsor, then the Pro shortcut', () => {
  render(<SponsorFooter />);
  const buttons = screen.getByRole('contentinfo').querySelectorAll('button');
  expect(Array.from(buttons, (button) => button.textContent)).toEqual([
    'integrationCatalog.title',
    'sponsorSlot.footer_brand',
    '',
  ]);
  expect(buttons[2]).toHaveAccessibleName('supportPlans.title');
  expect(screen.queryByRole('img')).toBeNull();
});

it('opens Integrations from the first button', () => {
  render(<SponsorFooter />);
  fireEvent.click(screen.getByRole('button', { name: 'integrationCatalog.title' }));
  expect(mock.navigate).toHaveBeenCalledWith({ to: '/integrations' });
});

it('opens the booking form from Become a Sponsor', () => {
  render(<SponsorFooter />);
  fireEvent.click(screen.getByRole('button', { name: 'sponsorSlot.footer_brand' }));
  expect(screen.getByRole('dialog')).toBeVisible();
  expect(mock.open).not.toHaveBeenCalled();
});

it('shows sourced audience details on sponsor focus', async () => {
  render(<SponsorFooter />);
  fireEvent.focus(screen.getByRole('button', { name: 'sponsorSlot.footer_brand' }));
  expect(await screen.findByText('sponsorSlot.footer_promo')).toBeVisible();
  expect(screen.getByText('22,678')).toBeVisible();
  expect(screen.getByText('207,236')).toBeVisible();
  expect(screen.getByText('35,336')).toBeVisible();
  expect(screen.getByText('sponsorSlot.footer_stats_note')).toBeVisible();
});

it('opens the Pro comparison from the right-hand X', () => {
  render(<SponsorFooter />);
  fireEvent.click(screen.getByRole('button', { name: 'supportPlans.title' }));
  expect(mock.navigate).toHaveBeenCalledWith({ to: '/pro' });
});

it('keeps the email fallback available from the booking form', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
  render(<SponsorFooter />);
  fireEvent.click(screen.getByRole('button', { name: 'sponsorSlot.footer_brand' }));
  fireEvent.click(screen.getByRole('tab', { name: 'sponsorSlot.email' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'sponsorSlot.message' }), {
    target: { value: 'My brand and website' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'sponsorSlot.copy_email' }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('partner@voicestudio.sh'));
  expect(screen.getByRole('textbox')).toHaveValue('My brand and website');
});
