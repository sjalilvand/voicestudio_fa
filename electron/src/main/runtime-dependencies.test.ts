// @vitest-environment node
import { afterEach, expect, it, vi } from 'vitest';
import { execFile } from 'node:child_process';
import { runtimeDependenciesReady, runtimePython } from './runtime-project';
vi.mock('node:child_process', () => ({ execFile: vi.fn() }));
afterEach(() => vi.clearAllMocks());
it.each([null, new Error('No module named uvicorn'), new Error('ETIMEDOUT'), new Error('ENOENT')])(
  'validates imports using the selected interpreter and fails closed (%s)',
  async (error) => {
    vi.mocked(execFile).mockImplementation(((
      _command: unknown,
      _args: unknown,
      _options: unknown,
      callback: (error: Error | null) => void,
    ) => callback(error)) as never);
    const project = '/runtime with spaces';
    expect(await runtimeDependenciesReady(project)).toBe(error === null);
    expect(execFile).toHaveBeenCalledWith(
      runtimePython(project),
      ['-c', 'import fastapi, uvicorn, omnivoice, faster_whisper'],
      expect.objectContaining({
        cwd: project,
        timeout: 30_000,
        windowsHide: true,
        env: expect.objectContaining({
          HF_HUB_OFFLINE: '1',
          TRANSFORMERS_OFFLINE: '1',
          PYTHONNOUSERSITE: '1',
        }),
      }),
      expect.any(Function),
    );
  },
);
