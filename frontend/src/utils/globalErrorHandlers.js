/**
 * globalErrorHandlers — last-resort surfacing for uncaught failures.
 *
 * consoleBuffer already records `window.onerror` / `unhandledrejection`
 * into the Settings → Logs → Frontend ring; this adds the user-visible
 * half: a throttled error toast with a "Report this bug" action
 * (utils/errorToast.jsx) so async failures outside any ErrorBoundary or
 * wired call site still have a path to a GitHub issue.
 *
 * Throttled per message (one toast per 30s) and filtered against known
 * benign noise — a render-loop bug must not bury the user in toasts.
 */
import i18next from 'i18next';
import { toastErrorWithReport } from './errorToast';

const THROTTLE_MS = 30_000;
const lastShown = new Map();

// Browser/webview noise that is not actionable by the user and must never
// produce a report prompt.
const IGNORE_PATTERNS = [
  /ResizeObserver loop/i,
  /AbortError/i,
  /Loading chunk \d+ failed/i, // transient on dev-server restarts
  /Script error\.?$/i, // opaque cross-origin errors carry no info
];

// A browser extension injected into the page throws in the page's own error
// channel, so `window.onerror` cannot tell it apart from ours by message alone
// — and the message-based list above cannot help, because an extension's
// TypeError reads exactly like one of ours. #1901 is the result: a report filed
// against VoiceStudio whose stack is entirely
// `chrome-extension://…/executors/200.js`, with no frame of ours in it.
//
// `Script error.` above already covers the opaque cross-origin case. An
// extension's script is not opaque, so it arrives with a full stack and slips
// straight through to the "Report this bug" action.
const EXTENSION_URL = /\b(?:chrome|moz|safari-web|safari|ms-browser)-extension:\/\//i;

/** The URL the error came FROM, or '' when the event carries no location. */
function originUrl(error, filename) {
  if (typeof filename === 'string' && filename) return filename;
  const stack = typeof error?.stack === 'string' ? error.stack : '';
  // First frame that names a URL — the throw site. Deliberately not "any frame
  // mentions an extension": an extension that patches a built-in leaves its
  // frame in the middle of a stack whose fault is genuinely ours, and dropping
  // those would silence real bugs.
  const match = stack.match(/(?:\(|@|\s)((?:[a-z-]+):\/\/[^\s)]+)/i);
  return match ? match[1] : '';
}

function shouldShow(message, error, filename) {
  // Some browser streams (including WaveSurfer's BodyStreamBuffer) describe
  // normal cancellation without the word "AbortError" in the message. The
  // structured DOMException name is the reliable cancellation contract.
  if (error?.name === 'AbortError') return false;
  if (EXTENSION_URL.test(originUrl(error, filename))) return false;
  if (!message || IGNORE_PATTERNS.some((p) => p.test(message))) return false;
  const key = String(message).slice(0, 200);
  const now = Date.now();
  if ((lastShown.get(key) || 0) > now - THROTTLE_MS) return false;
  lastShown.set(key, now);
  return true;
}

function surface(message, error, filename) {
  if (!shouldShow(message, error, filename)) return;
  const err = error instanceof Error ? error : new Error(String(error ?? message));
  toastErrorWithReport(
    i18next.t('errors.unexpected', { message: String(message).slice(0, 140) }),
    err,
  );
}

let installed = false;

export function installGlobalErrorHandlers() {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  window.addEventListener('error', (e) => {
    // `e.filename` is the script the throw came from — more reliable than
    // parsing a stack, and present even when the error object is not.
    surface(e?.error?.message || e.message, e.error, e?.filename);
  });
  window.addEventListener('unhandledrejection', (e) => {
    const r = e?.reason;
    surface(r?.message || String(r), r);
  });
}
