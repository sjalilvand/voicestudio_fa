import { LS_API_KEY, LS_BACKEND_URL } from '../api/client.ts';

export type RemoteProbeKind = 'tls' | 'cors' | 'network' | 'timeout' | 'http' | 'wrong_port';

export type RemoteProbeResult =
  | { ok: true; detail: string; target: string }
  | { ok: false; kind: RemoteProbeKind; status?: number; target: string };

const MAX_HEALTH_BYTES = 16 * 1024;

export function configuredRemoteBackend(): { url: string; key: string } | null {
  try {
    const url = localStorage.getItem(LS_BACKEND_URL)?.trim().replace(/\/+$/, '') || '';
    return url ? { url, key: localStorage.getItem(LS_API_KEY)?.trim() || '' } : null;
  } catch {
    return null;
  }
}

export function disableRemoteBackend(reload: () => void): void {
  try {
    localStorage.removeItem(LS_BACKEND_URL);
    localStorage.removeItem(LS_API_KEY);
  } finally {
    reload();
  }
}

function transportKind(url: URL, error: unknown): RemoteProbeKind {
  const text = String((error as Error)?.message || error).toLowerCase();
  if (url.port === '7443') return 'wrong_port';
  if ((error as Error)?.name === 'AbortError') return 'timeout';
  if (/certificate|cert_|ssl|tls/.test(text)) return 'tls';
  if (/cors|cross-origin/.test(text)) return 'cors';
  // Browser fetch deliberately hides DNS, connection, CORS, and TLS details
  // behind the same generic TypeError. Only report TLS when the error says so.
  return 'network';
}

async function readBoundedBody(response: Response): Promise<string | null> {
  const reader = response.body?.getReader();
  if (!reader) return null;

  const decoder = new TextDecoder();
  const parts: string[] = [];
  let bytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > MAX_HEALTH_BYTES) {
        await reader.cancel();
        return null;
      }
      parts.push(decoder.decode(value, { stream: true }));
    }
    parts.push(decoder.decode());
    return parts.join('');
  } finally {
    reader.releaseLock();
  }
}

export async function probeRemoteBackend(
  rawUrl: string,
  key = '',
  { fetchImpl = fetch, timeoutMs = 5000 }: { fetchImpl?: typeof fetch; timeoutMs?: number } = {},
): Promise<RemoteProbeResult> {
  const rawTarget = rawUrl.trim().replace(/\/+$/, '');
  let url: URL;
  try {
    url = new URL(rawTarget);
  } catch {
    return { ok: false, kind: 'network', target: rawTarget };
  }
  const hasEmbeddedCredentials = Boolean(url.username || url.password);
  const hasQueryOrFragment = Boolean(url.search || url.hash);
  url.username = '';
  url.password = '';
  url.search = '';
  url.hash = '';
  const target = url.toString().replace(/\/+$/, '');
  if (
    (url.protocol !== 'http:' && url.protocol !== 'https:') ||
    hasEmbeddedCredentials ||
    hasQueryOrFragment
  ) {
    return { ok: false, kind: 'network', target };
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(`${target}/health`, {
      headers: key ? { Authorization: `Bearer ${key}` } : {},
      signal: controller.signal,
      cache: 'no-store',
    });
    if (!response.ok) return { ok: false, kind: 'http', status: response.status, target };
    const advertisedBytes = Number(response.headers.get('content-length'));
    if (Number.isFinite(advertisedBytes) && advertisedBytes > MAX_HEALTH_BYTES) {
      return { ok: false, kind: 'wrong_port', target };
    }
    const payload = await readBoundedBody(response);
    if (payload === null) {
      return { ok: false, kind: 'wrong_port', target };
    }
    let body: unknown = null;
    try {
      body = JSON.parse(payload);
    } catch {
      // A healthy VoiceStudio API always returns a small JSON object.
    }
    if (
      !body ||
      typeof body !== 'object' ||
      (body as any).status !== 'ok' ||
      typeof (body as any).version !== 'string' ||
      typeof (body as any).device !== 'string'
    ) {
      return { ok: false, kind: 'wrong_port', target };
    }
    return {
      ok: true,
      detail: `${(body as any).version} on ${(body as any).device}`,
      target,
    };
  } catch (error) {
    return { ok: false, kind: transportKind(url, error), target };
  } finally {
    clearTimeout(timer);
  }
}
