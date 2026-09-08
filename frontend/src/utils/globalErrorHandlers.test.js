import { beforeEach, describe, expect, it, vi } from 'vitest';

const { toastErrorWithReport } = vi.hoisted(() => ({
  toastErrorWithReport: vi.fn(),
}));

vi.mock('./errorToast', () => ({ toastErrorWithReport }));

import { installGlobalErrorHandlers } from './globalErrorHandlers';

function dispatchUnhandledRejection(reason) {
  const event = new Event('unhandledrejection');
  Object.defineProperty(event, 'reason', { value: reason });
  window.dispatchEvent(event);
}

function dispatchError({ message, filename, error }) {
  const event = new Event('error');
  Object.defineProperty(event, 'message', { value: message });
  Object.defineProperty(event, 'filename', { value: filename });
  Object.defineProperty(event, 'error', { value: error });
  window.dispatchEvent(event);
}

/** An Error whose stack is entirely extension frames, as in #1901. */
function extensionError(message) {
  const err = new Error(message);
  err.stack = [
    `TypeError: ${message}`,
    '    at Y (chrome-extension://eppiocemhmnlbhjplcgkofciiegomcon/executors/200.js:1:761)',
    '    at E (chrome-extension://eppiocemhmnlbhjplcgkofciiegomcon/executors/200.js:1:1442)',
  ].join('\n');
  return err;
}

beforeEach(() => {
  toastErrorWithReport.mockClear();
});

describe('global unhandled rejection reporting', () => {
  it('ignores a named AbortError while still surfacing a real rejection', () => {
    installGlobalErrorHandlers();

    const cancelled = new DOMException('BodyStreamBuffer was aborted', 'AbortError');
    dispatchUnhandledRejection(cancelled);
    expect(toastErrorWithReport).not.toHaveBeenCalled();

    const failure = new Error('waveform request failed');
    dispatchUnhandledRejection(failure);
    expect(toastErrorWithReport).toHaveBeenCalledOnce();
    expect(toastErrorWithReport.mock.calls[0][1]).toBe(failure);
  });
});

/**
 * A browser extension throws into the page's own error channel, so the toast
 * offered "Report this bug" for code that is not ours. #1901 is one such
 * report: the stack is entirely
 * `chrome-extension://eppiocemhmnlbhjplcgkofciiegomcon/executors/200.js` with
 * no VoiceStudio frame in it, and the maintainer had no way to tell from the
 * message ("Cannot read properties of undefined") that it was not a real bug.
 *
 * The message-based IGNORE_PATTERNS cannot help here — an extension's TypeError
 * reads exactly like one of ours — and the existing `Script error.` entry only
 * covers the opaque cross-origin case. An extension's script is not opaque, so
 * it arrives with a full stack and goes straight through.
 *
 * consoleBuffer still records these into Settings → Logs → Frontend; what is
 * suppressed is the offer to file them against this project.
 */
describe('errors thrown by a browser extension', () => {
  it('does not offer to report an error event from an extension script', () => {
    installGlobalErrorHandlers();

    dispatchError({
      message: "Cannot read properties of undefined (reading 'M_ID')",
      filename: 'chrome-extension://eppiocemhmnlbhjplcgkofciiegomcon/executors/200.js',
      error: extensionError("Cannot read properties of undefined (reading 'M_ID')"),
    });

    expect(toastErrorWithReport).not.toHaveBeenCalled();
  });

  it('does not offer to report a rejection whose throw site is an extension', () => {
    installGlobalErrorHandlers();
    // No `filename` on an unhandledrejection, so the throw site has to come
    // off the stack.
    dispatchUnhandledRejection(extensionError('extension promise blew up'));

    expect(toastErrorWithReport).not.toHaveBeenCalled();
  });

  it('still reports our own error when an extension frame sits below it', () => {
    // The reason this filters on the THROW SITE and not on "any frame mentions
    // an extension": an extension that patches a built-in leaves its frame in
    // the middle of a stack whose fault is genuinely ours. Dropping those would
    // silence real bugs, which is worse than the noise it saves.
    installGlobalErrorHandlers();

    const ours = new Error('dub export failed');
    ours.stack = [
      'Error: dub export failed',
      '    at exportDub (http://tauri.localhost/assets/main-app.js:9:1)',
      '    at patched (chrome-extension://someid/inject.js:1:1)',
    ].join('\n');
    dispatchError({ message: ours.message, filename: undefined, error: ours });

    expect(toastErrorWithReport).toHaveBeenCalledOnce();
    expect(toastErrorWithReport.mock.calls[0][1]).toBe(ours);
  });
});
