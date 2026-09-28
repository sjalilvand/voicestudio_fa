import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { QualityControls } from './quality-controls';
import { cloneSettingsStore, DEFAULT_CLONE_SETTINGS } from '@/lib/store/clone-settings';

const engine = vi.hoisted(() => ({ id: 'omnivoice' }));
vi.mock('@/hooks/use-engines', () => ({ useEngines: () => ({ activeTts: engine }) }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: { size?: string }) => (params?.size ? `${key}: ${params.size}` : key),
  }),
}));

beforeEach(() => {
  // Base UI measures the track before exposing its keyboard input. jsdom has
  // no layout, so supply a real track size rather than bypassing accessibility.
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 300,
    bottom: 16,
    width: 300,
    height: 16,
    toJSON() {},
  });
  cloneSettingsStore.setState(() => ({ ...DEFAULT_CLONE_SETTINGS }));
  engine.id = 'omnivoice';
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it('changes export precision with the keyboard, updates size and keeps sampling independent', async () => {
  render(<QualityControls />);
  const precision = await screen.findByRole('slider', { name: 'cloneQuality.title' });
  expect(precision).toHaveAttribute('aria-valuetext', 'cloneQuality.bits16');
  expect(screen.getByText('cloneQuality.size: 2.75')).toBeInTheDocument();
  await act(async () => {
    fireEvent.keyDown(precision, { key: 'ArrowRight' });
  });
  expect(cloneSettingsStore.state.wavBits).toBe(24);
  expect(screen.getByText('cloneQuality.size: 4.12')).toBeInTheDocument();
  await act(async () => {
    fireEvent.keyDown(precision, { key: 'End' });
  });
  expect(cloneSettingsStore.state.wavBits).toBe(32);
  expect(screen.getByText('cloneQuality.size: 5.49')).toBeInTheDocument();
  expect(cloneSettingsStore.state.steps).toBe(16);
  fireEvent.click(screen.getByText('voiceControls.options'));
  await act(async () => {
    fireEvent.keyDown(screen.getByRole('slider', { name: 'cloneQuality.effort' }), {
      key: 'ArrowRight',
    });
  });
  expect(cloneSettingsStore.state.steps).toBe(17);
  expect(cloneSettingsStore.state.wavBits).toBe(32);
  fireEvent.click(screen.getByRole('switch', { name: 'cloneQuality.mastering' }));
  expect(cloneSettingsStore.state.effectPreset).toBe('raw');
});

it('hides unsupported sampling controls and disables quality changes while generating', async () => {
  engine.id = 'kitten';
  render(<QualityControls disabled />);
  expect(screen.queryByRole('slider', { name: 'cloneQuality.effort' })).toBeNull();
  expect(await screen.findByRole('slider')).toBeDisabled();
  fireEvent.click(screen.getByText('voiceControls.options'));
  expect(screen.getByRole('switch')).toHaveAttribute('aria-disabled', 'true');
});

it.each(['omnivoice-subprocess', 'voxcpm2', 'dots-tts', 'supertonic3'])(
  'offers only supported sampling ranges for %s',
  async (id) => {
    engine.id = id;
    render(<QualityControls />);
    fireEvent.click(screen.getByText('voiceControls.options'));
    const steps = await screen.findByRole('slider', { name: 'cloneQuality.effort' });
    expect(steps).toHaveAttribute('max', id === 'supertonic3' ? '12' : '64');
    await act(async () => {
      fireEvent.keyDown(steps, { key: 'Home' });
    });
    await act(async () => {
      fireEvent.keyDown(steps, { key: 'End' });
    });
    expect(cloneSettingsStore.state.steps).toBe(id === 'supertonic3' ? 12 : 64);
  },
);

it('keeps detailed tuning collapsed until requested', () => {
  const { container } = render(<QualityControls />);
  expect(container.querySelector('details')).not.toHaveAttribute('open');
  expect(screen.getByRole('switch')).not.toBeVisible();
  fireEvent.click(screen.getByText('voiceControls.options'));
  expect(screen.getByRole('switch', { name: 'cloneQuality.mastering' })).toBeVisible();
});
