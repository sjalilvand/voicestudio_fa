import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestDictationCapture, toast } = vi.hoisted(() => ({
  requestDictationCapture: vi.fn(),
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock('../utils/dictationCapture', () => ({ requestDictationCapture }));
vi.mock('../hooks/useEffectiveDictationShortcut', () => ({
  useEffectiveDictationShortcut: () => ({
    info: {
      accelerator: 'Super+Shift+V',
      display: 'Super+Shift+V',
      backend: 'portal',
    },
  }),
}));
vi.mock('react-hot-toast', () => ({ toast }));

import TranscriptionsPage, { addTranscription } from './Transcriptions';

describe('Transcriptions capture entry point', () => {
  beforeEach(() => {
    localStorage.clear();
    requestDictationCapture.mockReset().mockResolvedValue(undefined);
    toast.error.mockReset();
  });

  it('shows the effective shortcut and starts the shared recorder from the empty state', async () => {
    render(<TranscriptionsPage />);
    expect(screen.getByText(/Super\+Shift\+V/)).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button', { name: 'Start dictation' }).at(-1));
    await waitFor(() => expect(requestDictationCapture).toHaveBeenCalledWith('start'));
  });

  it('reports a capture-controller failure', async () => {
    requestDictationCapture.mockRejectedValueOnce(new Error('event channel unavailable'));
    render(<TranscriptionsPage />);
    fireEvent.click(screen.getAllByRole('button', { name: 'Start dictation' }).at(-1));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Could not start dictation.'));
  });

  it('shows a successful transcript emitted by the shared recorder', async () => {
    render(<TranscriptionsPage />);
    act(() => {
      addTranscription({ text: 'The shared capture path works.', language: 'en' });
    });

    expect(await screen.findByText('The shared capture path works.')).toBeInTheDocument();
  });
});
