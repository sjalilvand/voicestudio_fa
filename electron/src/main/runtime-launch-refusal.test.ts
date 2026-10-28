// @vitest-environment node
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { execFile, spawn, spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const host = vi.hoisted(() => ({ data: '' }));
const originalResources = Object.getOwnPropertyDescriptor(process, 'resourcesPath');
vi.mock('electron', () => ({ app: { isPackaged: true, getPath: () => host.data } }));
vi.mock('node:child_process', async (original) => ({
  ...(await original<typeof import('node:child_process')>()),
  execFile: vi.fn(),
  spawn: vi.fn(),
  spawnSync: vi.fn(),
}));
vi.mock('./runtime-project', async (original) => ({
  ...(await original<typeof import('./runtime-project')>()),
  // Structural metadata is intact; run the real dependency probe beneath it.
  runtimeReady: vi.fn(async () => true),
  runtimeCompatible: vi.fn(async () => false),
}));
import { runtimePython } from './runtime-project';
import { BackendSupervisor } from './backend';

beforeEach(async () => {
  host.data = await mkdtemp(join(tmpdir(), 'vs-launch-refusal-'));
  await mkdir(join(host.data, 'runtime', 'project', '.venv'), { recursive: true });
  Object.defineProperty(process, 'resourcesPath', { configurable: true, value: host.data });
  vi.spyOn(process, 'platform', 'get').mockReturnValue('win32');
  vi.spyOn(process, 'arch', 'get').mockReturnValue('x64');
  vi.stubEnv('OMNIVOICE_TORCH_VARIANT', 'cpu');
  vi.stubEnv('OMNIVOICE_BACKEND_CMD', '');
  vi.stubEnv('VOICESTUDIO_SKIP_BACKEND', '');
});
afterEach(async () => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  if (originalResources) Object.defineProperty(process, 'resourcesPath', originalResources);
  else delete (process as { resourcesPath?: string }).resourcesPath;
  await rm(host.data, { recursive: true, force: true });
});

function supervisor() {
  const value = new BackendSupervisor();
  vi.spyOn(value as unknown as { probe: () => Promise<boolean> }, 'probe').mockResolvedValue(false);
  const repair = vi.spyOn(value, 'setupRuntime').mockResolvedValue(undefined);
  return { value, repair };
}

function failProbe(mode: 'sync' | 'callback', code: string | number, stderr = '') {
  vi.mocked(execFile).mockImplementation(((
    _command: unknown,
    _args: unknown,
    _options: unknown,
    callback: (error: Error, stdout: string, stderr: string) => void,
  ) => {
    const error = Object.assign(new Error(code === 'UNKNOWN' ? 'spawn UNKNOWN' : 'launch failed'), {
      code,
    });
    if (mode === 'sync') throw error;
    callback(error, '', stderr);
  }) as never);
}

it.each([
  ['sync', 'UNKNOWN', 1, true],
  ['callback', 'UNKNOWN', 1, true],
  ['sync', 'UNKNOWN', 2, true],
  ['callback', 'UNKNOWN', 2, true],
  ['sync', 'UNKNOWN', 0, false],
  ['callback', 'UNKNOWN', 0, false],
  ['sync', 'EACCES', 0, false],
  ['callback', 'EACCES', 0, false],
  ['sync', 'EPERM', 0, false],
  ['callback', 'EPERM', 0, false],
] as const)(
  'reports %s %s refusal with SAC state %i without reinstalling',
  async (mode, code, sac, namesSac) => {
    failProbe(mode, code);
    vi.mocked(spawnSync).mockReturnValue({
      stdout: `VerifiedAndReputablePolicyState REG_DWORD 0x${sac}`,
    } as ReturnType<typeof spawnSync>);
    const { value, repair } = supervisor();

    await value.start();

    expect(value.status.stage).toBe('failed');
    expect(value.status.managed).toBe(false);
    expect(value.status.message).toContain(runtimePython(join(host.data, 'runtime', 'project')));
    expect(value.status.message?.includes('Windows Smart App Control blocked it.')).toBe(namesSac);
    expect(repair).not.toHaveBeenCalled();
    expect(spawn).not.toHaveBeenCalled();
  },
);

it.each(['sync', 'callback'] as const)(
  'still repairs a missing interpreter reported by %s ENOENT',
  async (mode) => {
    failProbe(mode, 'ENOENT');
    const { value, repair } = supervisor();
    await value.start();
    expect(repair).toHaveBeenCalledOnce();
    expect(value.status.stage).toBe('setup_required');
  },
);

it('still repairs a genuine missing-module failure', async () => {
  failProbe('callback', 1, "ModuleNotFoundError: No module named 'uvicorn'");
  const { value, repair } = supervisor();
  await value.start();
  expect(repair).toHaveBeenCalledOnce();
  expect(value.status.stage).toBe('setup_required');
});
