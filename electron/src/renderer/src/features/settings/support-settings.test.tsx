import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
const mock = vi.hoisted(() => ({ open: vi.fn().mockResolvedValue(undefined) }));
vi.mock('@/components/bridge', () => ({
  getBridge: () => ({ files: { openExternal: mock.open } }),
}));
vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));
import { SupportSettings } from './support-settings';
vi.mock('./donation-goal', () => ({ DonationGoal: () => null }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it('opens only the explicit destination and applies selected amounts only to PayPal', () => {
  render(<SupportSettings />);
  expect(mock.open).not.toHaveBeenCalled();
  const paypal = screen.getByRole('link', { name: 'PayPal' });
  expect(paypal).toHaveAttribute('href', 'https://paypal.me/palashCoder');
  fireEvent.click(screen.getByRole('button', { name: '$20' }));
  expect(paypal).toHaveAttribute('href', 'https://paypal.me/palashCoder/20');
  expect(screen.getByRole('link', { name: 'Ko-fi' })).toHaveAttribute(
    'href',
    'https://ko-fi.com/debpalash',
  );
  fireEvent.click(paypal);
  expect(mock.open).toHaveBeenCalledOnce();
  expect(mock.open).toHaveBeenCalledWith('https://paypal.me/palashCoder/20');
  expect(screen.getByRole('link', { name: 'contact.security_cta' })).toHaveAttribute(
    'href',
    'https://github.com/debpalash/VoiceStudio/security/advisories/new',
  );
  expect(screen.getByRole('link', { name: 'support.sponsors_become' })).toHaveAttribute(
    'href',
    'https://github.com/debpalash/VoiceStudio/issues/new?template=sponsor.yml',
  );
  const license = new URL(
    screen.getByRole('link', { name: 'enterprise.request_quote' }).getAttribute('href')!,
  );
  expect(license.protocol).toBe('mailto:');
  expect(license.searchParams.get('subject')).toBe('VoiceStudio Commercial License Inquiry');
  expect(license.searchParams.get('body')).toContain('Use case:');
});
