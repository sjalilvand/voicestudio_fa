import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import '@/i18n';
import { LanguagePicker } from './language-picker';

vi.mock('@/lib/languages', () => ({
  LANGUAGES: ['Auto', 'English', 'Japanese'],
  POPULAR_LANGUAGES: ['English'],
}));
const select = vi.hoisted(() => vi.fn());
vi.mock('@/lib/store/clone-settings', () => ({
  useCloneSetting: () => 'Auto',
  setCloneSetting: select,
}));

it('shows language options after the popover mounts and supports filtered selection', async () => {
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(320);
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(340);
  render(<LanguagePicker />);
  fireEvent.click(screen.getByRole('button', { name: 'Language' }));
  expect((await screen.findAllByRole('option', { name: 'English' })).length).toBeGreaterThan(0);
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Japanese' } });
  fireEvent.click(await screen.findByRole('option', { name: 'Japanese' }));
  expect(select).toHaveBeenCalledWith('language', 'Japanese');
});
