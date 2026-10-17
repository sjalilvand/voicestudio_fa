import { _electron as electron } from 'playwright';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { startHealthBackend } from './fake-health-backend.mjs';
import { isAllowedRequest, STAR_COUNT_STUB, STAR_COUNT_URL } from './local-first.mjs';

const workspaceRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
export const ARTIFACT_DIR = join(workspaceRoot, 'electron/test-results', process.platform);

/**
 * Console errors tolerated across a run. Each entry needs a comment saying why the app
 * legitimately emits it; an unexplained entry hides real regressions.
 */
export const ALLOWED_CONSOLE_ERRORS = [];

export function electronExecutable() {
  const dist = join(workspaceRoot, 'electron/node_modules/electron/dist');
  if (process.platform === 'win32') return join(dist, 'electron.exe');
  if (process.platform === 'darwin') return join(dist, 'Electron.app/Contents/MacOS/Electron');
  return join(dist, 'electron');
}

/** Latin non-ASCII plus a space, so path-encoding bugs in user-data handling surface per OS. */
export const makeProfile = () => mkdtempSync(join(tmpdir(), 'VoiceStudio Tëst '));

/** A loopback port with nothing listening on it. */
export const freePort = () =>
  new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolvePort(port));
    });
  });

const slug = (name) => name.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase();

async function launch({ profile, backendPort, proxyPort, seed }) {
  // VS Code terminals export ELECTRON_RUN_AS_NODE=1, which makes Electron boot as plain Node.
  const { ELECTRON_RUN_AS_NODE: _runAsNode, ...inherited } = process.env;
  const app = await electron.launch({
    executablePath: electronExecutable(),
    args: [join(workspaceRoot, 'electron/out/main/index.js'), '--user-data-dir=' + profile],
    env: {
      ...inherited,
      ELECTRON_RENDERER_URL: '',
      OMNIVOICE_PORT: String(backendPort),
      VOICESTUDIO_SKIP_BACKEND: '1',
      VOICESTUDIO_ALLOW_MULTIPLE_INSTANCES: '1',
      VOICESTUDIO_DISABLE_UPDATER: '1',
      VOICESTUDIO_ELECTRON_PROXY_PORT: String(proxyPort),
    },
    timeout: 60000,
  });
  const context = app.context();
  await context.tracing.start({ screenshots: true, snapshots: true });
  await context.route(STAR_COUNT_URL, (route) => route.fulfill({ json: STAR_COUNT_STUB }));
  if (seed) {
    // Only fill gaps: this runs on every page load and must not undo what a test persisted.
    await context.addInitScript(() => {
      for (const [key, value] of [
        ['voicestudio.setup.complete.v1', '1'],
        ['voicestudio.locale', 'en'],
      ]) {
        if (localStorage.getItem(key) === null) localStorage.setItem(key, value);
      }
    });
  }
  await app.evaluate(({ session }) => {
    const seen = (globalThis.__requestLog = []);
    session.defaultSession.webRequest.onBeforeRequest((details, callback) => {
      seen.push(details.url);
      callback({});
    });
  });
  const page = await app.firstWindow();
  const errors = [];
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const text = message.text();
    if (!ALLOWED_CONSOLE_ERRORS.some((pattern) => pattern.test(text))) {
      errors.push(`console: ${text}`);
    }
  });
  // Requests made before the hooks existed are replayed by one reload.
  await page.reload();
  return { app, page, errors };
}

/**
 * Runs `body` against a freshly launched desktop app and enforces the run-wide guards:
 * every request stays local, no renderer errors, no main-process errors. On failure the
 * trace, a screenshot and the app logs are saved to ARTIFACT_DIR/<test name>/.
 */
export async function withApp(t, options, body) {
  const { profile: given, fixtures, seed = true, backend: backendMode = 'up' } = options;
  const profile = given ?? makeProfile();
  const backend = backendMode === 'up' ? await startHealthBackend({ fixtures }) : null;
  const backendPort = backend ? backend.port : await freePort();
  const proxyPort = await freePort();
  const live = [];
  const session = { profile, backend, relaunch: null };
  const start = async () => {
    const started = await launch({ profile, backendPort, proxyPort, seed });
    live.push(started);
    Object.assign(session, started);
    return session;
  };
  session.relaunch = async () => {
    const previous = live.at(-1);
    await collectGuards(previous);
    // Closing an app that was killed mid-test rejects; the process is gone either way.
    await previous.app.close().catch(() => {});
    return start();
  };
  const violations = [];
  const errors = [];
  async function collectGuards(started) {
    const seen = await started.app.evaluate(() => globalThis.__requestLog ?? []).catch(() => []);
    violations.push(...seen.filter((url) => url !== STAR_COUNT_URL && !isAllowedRequest(url)));
    errors.push(...started.errors);
  }
  try {
    await start();
    await body(session);
    await collectGuards(live.at(-1));
    assert.deepEqual(violations, [], 'Requests left the machine');
    assert.deepEqual(errors, [], 'Renderer reported errors');
    const journal = join(profile, 'main-process-errors.json');
    if (existsSync(journal)) {
      const entries = JSON.parse(readFileSync(journal, 'utf8'));
      assert.deepEqual(entries.length ? entries : [], [], 'Main process journaled errors');
    }
  } catch (error) {
    await saveArtifacts(t.name, live.at(-1), profile).catch(() => {});
    throw error;
  } finally {
    for (const started of live) await started.app.close().catch(() => {});
    await backend?.close();
    if (!given) rmSync(profile, { recursive: true, force: true });
  }
}

async function saveArtifacts(name, started, profile) {
  if (!started) return;
  const dir = join(ARTIFACT_DIR, slug(name));
  mkdirSync(dir, { recursive: true });
  await started.page.screenshot({ path: join(dir, 'final.png') }).catch(() => {});
  await started.app.context().tracing.stop({ path: join(dir, 'trace.zip') });
  const logs = await started.app.evaluate(({ app }) => app.getPath('logs')).catch(() => null);
  if (logs && existsSync(logs)) cpSync(logs, join(dir, 'logs'), { recursive: true });
  const journal = join(profile, 'main-process-errors.json');
  if (existsSync(journal)) cpSync(journal, join(dir, 'main-process-errors.json'));
}
