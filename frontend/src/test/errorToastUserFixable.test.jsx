// #1188: backend errors carrying a machine-readable "[code]" marker are
// user-fixable input problems, not bugs. toastErrorWithReport must map the
// [clone_ref_unusable] marker (emitted by omnivoice/utils/audio.py when a
// clone reference clip has genuinely no audio) to the localized guidance in
// tts_errors.ref_audio_unusable — a plain toast, no "Report this bug" action.
// Pins both halves of the cross-layer contract: the marker string and the
// i18n key existing in every locale.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const { toastMock, toastErrorMock } = vi.hoisted(() => {
  const error = vi.fn();
  const mock = Object.assign(vi.fn(), { error, dismiss: vi.fn() });
  return { toastMock: mock, toastErrorMock: error };
});
vi.mock('react-hot-toast', () => ({ default: toastMock, toast: toastMock }));
vi.mock('i18next', () => ({ default: { t: (k) => `t:${k}` } }));
vi.mock('../api/external', () => ({ openExternal: vi.fn() }));
vi.mock('../utils/bugReport', () => ({ buildBugReportUrl: vi.fn() }));

import { toastErrorWithReport } from '../utils/errorToast';

const BACKEND_ERROR =
  '400 Bad Request: [clone_ref_unusable] Reference audio has no usable sound — ' +
  'the clip is empty or completely silent, so there is no voice to clone.';

describe('toastErrorWithReport user-fixable marker mapping (#1188)', () => {
  beforeEach(() => {
    toastErrorMock.mockClear();
  });

  it('shows the localized guidance for [clone_ref_unusable] instead of the raw detail', () => {
    toastErrorWithReport(`Error: ${BACKEND_ERROR}`, new Error(BACKEND_ERROR));
    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    expect(toastErrorMock).toHaveBeenCalledWith('t:tts_errors.ref_audio_unusable', {
      duration: 8000,
    });
  });

  it('matches the marker even when only the message string carries it', () => {
    toastErrorWithReport(`Error: ${BACKEND_ERROR}`, undefined);
    expect(toastErrorMock).toHaveBeenCalledWith('t:tts_errors.ref_audio_unusable', {
      duration: 8000,
    });
  });

  it('unmarked errors keep the Report-action toast (JSX renderer, not a plain string)', () => {
    toastErrorWithReport('Error: something exploded', new Error('something exploded'));
    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    expect(typeof toastErrorMock.mock.calls[0][0]).toBe('function');
  });

  it('tts_errors.ref_audio_unusable exists (non-empty) in every locale', () => {
    const localesDir = path.resolve(__dirname, '../i18n/locales');
    const files = fs.readdirSync(localesDir).filter((f) => f.endsWith('.json'));
    expect(files.length).toBeGreaterThanOrEqual(21);
    for (const f of files) {
      const locale = JSON.parse(fs.readFileSync(path.join(localesDir, f), 'utf8'));
      expect(locale.tts_errors?.ref_audio_unusable, `${f} missing the key`).toBeTruthy();
    }
  });
});
