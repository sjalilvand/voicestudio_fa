import { createServer } from 'node:http';
import assert from 'node:assert/strict';

const DEFAULT_FIXTURES = {
  '/health': { status: 'ok', version: 'native-smoke' },
  '/setup/status': { models_ready: true, missing: [] },
  '/api/settings/analytics': { available: false, prompted: true, opted_in: false },
  '/engines': {},
  '/profiles': [],
  '/models': { models: [] },
  '/dictation/prefs': { enabled: false, mode: 'toggle', model_id: null },
  '/dictation/models': { engine_available: false, models: [] },
  '/batch/jobs': [],
  '/history': [],
  '/api/settings/performance-profile': { profile: 'balanced', engines: {} },
  '/model/status': { status: 'not_loaded', message: '' },
  '/model/loaded': { models: [] },
  '/engines/translation': { active: null, engines: [] },
  '/engines/diarisation': { active: null, engines: [] },
  '/system/notifications': [],
  '/export/history': [],
  '/projects': [],
};

const readBody = (request) =>
  new Promise((resolve, reject) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.once('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    request.once('error', reject);
  });

/**
 * Minimal external backend for native tests whose API traffic is intercepted in Playwright.
 *
 * `fixtures` is merged over the defaults; a value may be a function `(request, body) => json`.
 * Every request is appended to `requests` before its response is written.
 */
export async function startHealthBackend({ fixtures = {} } = {}) {
  const served = { ...DEFAULT_FIXTURES, ...fixtures };
  const requests = [];
  const server = createServer(async (request, response) => {
    const path = new URL(request.url ?? '/', 'http://127.0.0.1').pathname;
    const body = await readBody(request);
    const known = Object.hasOwn(served, path);
    requests.push({ method: request.method ?? 'GET', path, status: known ? 200 : 404, body });
    if (known) {
      const fixture = served[path];
      response.writeHead(200, {
        'content-type': 'application/json',
        'x-omnivoice-backend': 'native-smoke',
      });
      response.end(JSON.stringify(typeof fixture === 'function' ? fixture(request, body) : fixture));
      return;
    }
    response.writeHead(404);
    response.end();
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  assert(address && typeof address !== 'string');
  return {
    port: address.port,
    requests,
    close: () => {
      server.closeAllConnections();
      return new Promise((resolve) => server.close(resolve));
    },
  };
}
