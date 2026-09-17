import { clearConversion } from './conversion-state';
import { cleanup, fireEvent, render, screen, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
const mock = vi.hoisted(() => ({ convert: vi.fn() }));
vi.mock('@/lib/api/convert', () => ({ convertSpeech: mock.convert }));
vi.mock('@/hooks/use-recording', () => ({
  useRecording: () => ({ isRecording: false, isStarting: false, isCleaning: false }),
}));
vi.mock('@/hooks/use-profiles', () => ({
  useProfiles: () => ({
    data: [{ id: 'a', name: 'Alpha', kind: 'clone', ref_audio_path: 'a.wav' }],
  }),
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/components/waveform-player', () => ({
  WaveformPlayer: ({ src, source }: { src: string; source: string }) => (
    <div data-testid={source}>{src}</div>
  ),
}));
import { ConvertVoice } from './convert-voice';
afterEach(() => {
  cleanup();
  clearConversion();
  vi.clearAllMocks();
});
function mount() {
  const view = render(
    <QueryClientProvider client={new QueryClient()}>
      <ConvertVoice />
    </QueryClientProvider>,
  );
  const upload = (name = 'source.wav') =>
    fireEvent.change(screen.getByLabelText('convert.source_kicker', { selector: 'input' }), {
      target: { files: [new File(['source audio'], name, { type: 'audio/wav' })] },
    });
  return { ...view, upload };
}
it('requires source and target, posts independent inputs and plays returned audio', async () => {
  mock.convert.mockResolvedValue({ id: 'x', audio_url: '/audio/x.wav', text: 'Recognized source' });
  const { upload } = mount();
  const button = screen.getByRole('button', { name: 'convert.convert' });
  expect(button).toBeDisabled();
  upload();
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Alpha' }));
  fireEvent.click(button);
  expect(await screen.findByTestId('convert-result')).toHaveTextContent('/api/audio/x.wav');
  expect(mock.convert).toHaveBeenCalledWith(expect.any(File), 'a', true, expect.any(AbortSignal));
  expect(screen.getByText('Recognized source')).toBeInTheDocument();
});
it('cancels obsolete conversion and ignores a late response after source changes', async () => {
  let finish!: (value: unknown) => void;
  mock.convert.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const { upload } = mount();
  upload();
  fireEvent.click(screen.getByRole('button', { name: 'Alpha' }));
  fireEvent.click(screen.getByRole('button', { name: 'convert.convert' }));
  const signal = mock.convert.mock.calls[0][3];
  upload('replacement.wav');
  expect(signal.aborted).toBe(true);
  await act(async () => finish({ audio_url: '/audio/stale.wav', text: 'obsolete' }));
  expect(screen.queryByTestId('convert-result')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'convert.convert' })).toBeEnabled();
});

it('retains source and target when returning from model settings', () => {
  const first = mount();
  first.upload();
  fireEvent.click(screen.getByRole('button', { name: 'Alpha' }));
  first.unmount();
  mount();
  expect(screen.getByRole('button', { name: 'Alpha' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('button', { name: 'source.wav' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'convert.convert' })).toBeEnabled();
});
