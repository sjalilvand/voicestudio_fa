import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import i18n from '../../i18n';
import EngineWeights, { weightsForEngine } from './EngineWeights';

vi.mock('../DictationModelPicker', () => ({
  default: () => <div data-testid="dictation-model-picker-stub" />,
}));

const t = i18n.t.bind(i18n);

const MODELS = [
  {
    repo_id: 'k2-fsa/OmniVoice',
    label: 'VoiceStudio TTS',
    role: 'TTS',
    size_gb: 2.4,
    size_on_disk_bytes: 3.04 * 1024 ** 3,
    installed: true,
    required: true,
    engines: ['omnivoice', 'omnivoice-subprocess'],
  },
  {
    repo_id: 'openbmb/VoxCPM2',
    label: 'VoxCPM2',
    role: 'TTS',
    size_gb: 5,
    installed: false,
    curated: true,
    engines: ['voxcpm2'],
  },
  {
    repo_id: 'pyannote/speaker-diarization-3.1',
    label: 'Diarisation',
    role: 'Diarisation',
    size_gb: 0.8,
    installed: false,
    engines: [],
  },
  { repo_id: 'legacy/no-mapping', label: 'Legacy', role: 'TTS', size_gb: 1, installed: false },
];

const IDLE = {
  showBar: false,
  isInstalling: false,
  isDeleting: false,
  rowBusy: false,
  unsupported: false,
};

function downloads(over = {}) {
  return {
    speedRef: { current: {} },
    getRowRuntime: () => IDLE,
    getResidency: () => null,
    onInstall: vi.fn(),
    onDelete: vi.fn(),
    onReinstall: vi.fn(),
    onCancel: vi.fn(),
    onDismissError: vi.fn(),
    onUnload: vi.fn(),
    ...over,
  };
}

describe('weightsForEngine', () => {
  it('returns only rows whose engines list names the engine (unmapped rows never leak)', () => {
    expect(weightsForEngine(MODELS, 'omnivoice').map((m) => m.repo_id)).toEqual([
      'k2-fsa/OmniVoice',
    ]);
    expect(weightsForEngine(MODELS, 'omnivoice-subprocess')).toHaveLength(1);
    expect(weightsForEngine(MODELS, 'voxcpm2')).toHaveLength(1);
    expect(weightsForEngine(MODELS, 'kittentts')).toEqual([]);
    expect(weightsForEngine(undefined, 'omnivoice')).toEqual([]);
  });
});

describe('EngineWeights', () => {
  it('lists an engine’s weights one line each: state tick, label, tags, size, one action', () => {
    const d = downloads();
    render(<EngineWeights engineId="omnivoice" models={MODELS} downloads={d} t={t} />);
    const row = screen.getByTestId('weight-k2-fsa/OmniVoice');
    expect(row).toHaveAttribute('data-installed', 'true');
    expect(within(row).getByText('VoiceStudio TTS')).toBeInTheDocument();
    expect(within(row).getByText(t('models.required_tag'))).toBeInTheDocument();
    expect(within(row).getByText('3.04 GB')).toBeInTheDocument();
    // Installed: remove + reinstall, no Install.
    fireEvent.click(within(row).getByRole('button', { name: /delete/i }));
    expect(d.onDelete).toHaveBeenCalledWith('k2-fsa/OmniVoice');
    expect(within(row).queryByTestId('weight-install-k2-fsa/OmniVoice')).toBeNull();
    // Other engines' weights are not here.
    expect(screen.queryByTestId('weight-openbmb/VoxCPM2')).toBeNull();
  });

  it('offers Install on a missing weight and marks the curated pick', () => {
    const d = downloads();
    render(<EngineWeights engineId="voxcpm2" models={MODELS} downloads={d} t={t} />);
    const row = screen.getByTestId('weight-openbmb/VoxCPM2');
    expect(within(row).getByText(t('voicePanel.badge_recommended'))).toBeInTheDocument();
    expect(within(row).getByText('5 GB')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('weight-install-openbmb/VoxCPM2'));
    expect(d.onInstall).toHaveBeenCalledWith('openbmb/VoxCPM2');
  });

  it('shows progress with a cancel action while a download runs, and an error with Retry after', () => {
    const running = {
      ...IDLE,
      showBar: true,
      isInstalling: true,
      aggPct: 42,
      hasFiles: true,
      agg: {},
      dispDownloaded: 2 * 1024 ** 3,
      dispTotal: 5 * 1024 ** 3,
      aggRate: 50 * 1024 ** 2,
      fileList: [],
    };
    const d = downloads({ getRowRuntime: () => running });
    const { rerender } = render(
      <EngineWeights engineId="voxcpm2" models={MODELS} downloads={d} t={t} />,
    );
    const progress = screen.getByTestId('weight-progress-openbmb/VoxCPM2');
    expect(progress).toHaveTextContent('42%');
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(d.onCancel).toHaveBeenCalledWith('openbmb/VoxCPM2');

    const failed = { ...IDLE, phase: 'install_error', rs: { error: 'gated repo' } };
    rerender(
      <EngineWeights
        engineId="voxcpm2"
        models={MODELS}
        downloads={downloads({
          getRowRuntime: () => failed,
          onInstall: d.onInstall,
          onDismissError: d.onDismissError,
        })}
        t={t}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('gated repo');
    fireEvent.click(screen.getByRole('button', { name: t('models.retry_btn') }));
    expect(d.onInstall).toHaveBeenCalledWith('openbmb/VoxCPM2');
    fireEvent.click(screen.getByRole('button', { name: t('common.dismiss') }));
    expect(d.onDismissError).toHaveBeenCalledWith('openbmb/VoxCPM2');
  });

  it('says so when an engine has no catalogue weights, and renders nothing without a download host', () => {
    render(<EngineWeights engineId="funasr" models={MODELS} downloads={downloads()} t={t} />);
    expect(screen.getByTestId('engine-weights-none')).toHaveTextContent(t('engines.noWeights'));
    const { container } = render(
      <EngineWeights engineId="omnivoice" models={MODELS} downloads={null} t={t} />,
    );
    expect(container.querySelector('[data-testid="engine-weights-omnivoice"]')).toBeNull();
  });

  it('hands the sherpa-onnx dictation engine to its own model picker', () => {
    render(
      <EngineWeights engineId="sherpa-onnx-asr" models={MODELS} downloads={downloads()} t={t} />,
    );
    expect(screen.getByTestId('dictation-model-picker-stub')).toBeInTheDocument();
  });
});
