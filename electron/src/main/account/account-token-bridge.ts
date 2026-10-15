import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import type { AccessToken } from './account-session';

/**
 * Backend-only capability (guide §2 "Giving tokens to the Python backend").
 * The refresh token never leaves main; the backend gets a short-lived access
 * token only while sync is on and the backend is the local one.
 */
export async function startAccountTokenBridge(deps: {
  getToken: () => Promise<AccessToken | null>;
  isSyncAllowed: () => boolean;
  isRemoteBackend: () => boolean;
}): Promise<{ url: string; token: string; close(): void }> {
  const token = randomBytes(32).toString('hex');
  const expected = Buffer.from('Bearer ' + token);
  const server = createServer(async (req, res) => {
    const send = (status: number, data: unknown) => {
      res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
      res.end(JSON.stringify(data));
    };
    const supplied = Buffer.from(req.headers.authorization || '');
    if (
      supplied.length !== expected.length ||
      !timingSafeEqual(supplied, expected) ||
      req.headers.origin
    )
      return send(403, { error: 'Forbidden' });
    if (req.method !== 'GET' || req.url !== '/token') return send(404, { error: 'Not found' });
    if (!deps.isSyncAllowed() || deps.isRemoteBackend()) return send(200, { signed_in: false });
    try {
      const access = await deps.getToken();
      return send(200, access ? { signed_in: true, ...access } : { signed_in: false });
    } catch {
      return send(503, { signed_in: false, retry: true });
    }
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve());
  });
  const { port } = server.address() as AddressInfo;
  return { url: `http://127.0.0.1:${port}`, token, close: () => server.close() };
}
