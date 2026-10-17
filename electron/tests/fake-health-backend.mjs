import { createHash } from 'node:crypto';
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
  '/models/install/status': { jobs: [] },
  '/generate/budget': {},
  '/setup/preflight': {
    ok: true,
    checks: [{ id: 'ram', label: 'Memory', status: 'pass', detail: 'Enough memory', fix: null }],
  },
  // Matches `/setup/status` above: every model is already installed.
  '/setup/recommendations': {
    device: { label: 'Fixture CPU' },
    models: [
      {
        repo_id: 'k2-fsa/OmniVoice',
        label: 'VoiceStudio TTS',
        role: 'TTS',
        size_gb: 2.4,
        required: true,
        installed: true,
      },
    ],
    download_gb_remaining: 0,
    total_gb: 2.4,
    all_installed: true,
  },
  '/dictation/readiness': { ready: true },
  // HEAD probe for the bundled dictation demo clip shown on the last setup step.
  '/demo_audio/dictation/en_conversational.wav': {},
  '/system/info': { translate_provider: 'unknown' },
  '/watermark/status': { audioseal_available: true, invisible_enabled: true },
  '/api/settings/history-retention': { cap: 200, default: 200 },
  '/media-tools/status': {
    tools: {
      ffmpeg: { ok: true, version: 'fixture', origin: 'system' },
      ffprobe: { ok: true, origin: 'system' },
      ytdlp: { version: 'fixture', overlay_version: null },
    },
    ops: {},
  },
};

const WEBSOCKET_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

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
  const sockets = new Set(); // upgraded sockets are invisible to closeAllConnections()
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
  // The app opens /ws/events for live status; accept the handshake and never send a frame.
  server.on('upgrade', (request, socket) => {
    const key = request.headers['sec-websocket-key'];
    if (typeof key !== 'string') {
      socket.destroy();
      return;
    }
    const accept = createHash('sha1')
      .update(key + WEBSOCKET_GUID)
      .digest('base64');
    socket.write(
      'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n' +
        `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
    );
    sockets.add(socket);
    socket.on('error', () => {});
    socket.once('close', () => sockets.delete(socket));
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
      for (const socket of sockets) socket.destroy();
      return new Promise((resolve) => server.close(resolve));
    },
  };
}
