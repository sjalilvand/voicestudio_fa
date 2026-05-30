// Backend base URL. Configurable via VITE_API_URL or VITE_API_PORT env vars.
// In production Tauri builds, the webview talks to the sidecar on localhost.
const viteEnv = import.meta.env ?? {};
const _port = viteEnv.VITE_API_PORT || '3900';
// In Tauri builds the backend is always on localhost; in Docker/remote deployments
// use window.location.hostname so the browser can reach the server remotely.
const _host =
  typeof window !== 'undefined' && window.__TAURI__
    ? '127.0.0.1'
    : (typeof window !== 'undefined' ? window.location.hostname : '127.0.0.1');
export const API = viteEnv.VITE_API_URL || `http://${_host}:${_port}`;

// Capture a QR-supplied PIN once on load. When LAN sharing is on, the host's
// QR code links to `http://<lan-ip>:<port>/?pin=<pin>`; stash it in
// sessionStorage so apiFetch attaches it to every request automatically.
if (typeof window !== 'undefined') {
  try {
    const p = new URL(window.location.href).searchParams.get('pin');
    if (p) sessionStorage.setItem('ov_pin', p);
  } catch { /* noop */ }
}

export class ApiError extends Error {
  status?: number;
  detail?: unknown;
  constructor(message: string, init: { status?: number; detail?: unknown } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = init.status;
    this.detail = init.detail;
  }
}

export function apiUrl(path?: string): string {
  if (!path) return API;
  return path.startsWith('http') ? path : `${API}${path.startsWith('/') ? '' : '/'}${path}`;
}

async function readError(res: Response): Promise<string> {
  const text = await res.text().catch(() => '');
  try {
    const j = JSON.parse(text);
    return j.detail || j.error || text || res.statusText;
  } catch {
    return text || res.statusText;
  }
}

export async function apiFetch(path: string, opts: RequestInit = {}): Promise<Response> {
  const pin = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('ov_pin') : null;
  // Only modify the request when a PIN is set, so the default call shape
  // (e.g. FormData posts with no headers / no Content-Type override) is
  // preserved exactly.
  const finalOpts: RequestInit = pin
    ? { ...opts, headers: { ...(opts.headers as Record<string, string> || {}), 'X-OmniVoice-Pin': pin } }
    : opts;
  const res = await fetch(apiUrl(path), finalOpts);
  if (!res.ok) {
    // 401 from the LAN PIN middleware on a remote device → surface the gate.
    if (res.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new Event('ov:pin-required'));
    }
    const detail = await readError(res);
    throw new ApiError(`${res.status} ${res.statusText}: ${detail}`, { status: res.status, detail });
  }
  return res;
}

export async function apiJson<T = unknown>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, opts);
  return res.json() as Promise<T>;
}

export async function apiPost<T = unknown>(
  path: string,
  body?: unknown,
  opts: RequestInit = {},
): Promise<T> {
  const init: RequestInit = { method: 'POST', ...opts };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json', ...(opts.headers as Record<string, string> || {}) };
    init.body = JSON.stringify(body);
  }
  return apiJson<T>(path, init);
}

export async function apiDelete(path: string, opts: RequestInit = {}): Promise<Response> {
  return apiFetch(path, { method: 'DELETE', ...opts });
}
