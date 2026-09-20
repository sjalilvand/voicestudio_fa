// @vitest-environment node
import { afterEach, expect, it, vi } from 'vitest';
import { join, resolve } from 'node:path';
const state = vi.hoisted(() => ({ installed: true, packaged: false, ready: true }));
vi.mock('electron', () => ({
  app: {
    get isPackaged() {
      return state.packaged;
    },
    getAppPath: () => resolve('/repo/electron'),
    getPath: () => '/user-data',
  },
}));
vi.mock('node:fs', async (importOriginal) => ({
  ...(await importOriginal<typeof import('node:fs')>()),
  existsSync: (path: string) =>
    path === join(resolve('/repo'), 'backend', 'main.py') ||
    path === join(resolve('/repo'), 'pyproject.toml') ||
    (path.includes('.venv') ? state.installed : path.includes('uv')),
  statSync: () => ({ isFile: () => true, size: 1 }),
  accessSync: () => undefined,
}));
vi.mock('./runtime-project', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./runtime-project')>()),
  runtimeDependenciesReady: vi.fn(async () => state.ready),
}));
import { resolveSpawnPlan } from './backend';
afterEach(() => {
  state.installed = true;
  state.ready = true;
  state.packaged = false;
  vi.unstubAllEnvs();
});
it('launches the prepared source interpreter without syncing or downloading dependencies', async () => {
  vi.stubEnv('OMNIVOICE_BACKEND_CMD', '');
  const plan = await resolveSpawnPlan(3912);
  expect(plan).toHaveProperty('argv');
  if ('error' in plan) throw new Error(plan.error);
  expect(plan.argv[0]).toBe(
    join(
      resolve('/repo'),
      '.venv',
      process.platform === 'win32' ? 'Scripts' : 'bin',
      process.platform === 'win32' ? 'python.exe' : 'python',
    ),
  );
  expect(plan.argv.slice(1, 3)).toEqual(['-m', 'uvicorn']);
  expect(plan.argv.slice(-2)).toEqual(['--port', '3912']);
});
it('requires explicit source setup when no environment exists, even with uv installed', async () => {
  vi.stubEnv('OMNIVOICE_BACKEND_CMD', '');
  state.installed = false;
  expect(await resolveSpawnPlan(3900)).toEqual({
    error: expect.stringContaining('bun run setup:api'),
  });
});
it('preserves an explicitly configured command', async () => {
  vi.stubEnv('OMNIVOICE_BACKEND_CMD', '["custom-python", "-m", "uvicorn"]');
  expect(await resolveSpawnPlan(3900)).toHaveProperty('argv', ['custom-python', '-m', 'uvicorn']);
});

it('requires setup when an interpreter exists but required imports fail', async () => {
  vi.stubEnv('OMNIVOICE_BACKEND_CMD', '');
  state.ready = false;
  expect(await resolveSpawnPlan(3900)).toEqual({
    error: expect.stringContaining('bun run setup:api'),
  });
});
