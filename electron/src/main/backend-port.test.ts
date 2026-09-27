// @vitest-environment node
import { EventEmitter } from 'node:events';
import { afterEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  spawn: vi.fn(),
  listen: vi.fn(),
  bindError: 'EACCES' as string | null,
  close: vi.fn(),
}));
vi.mock('electron', () => ({ app: { isPackaged: true, getPath: () => '/unused-port-test' } }));
vi.mock('node:child_process', () => ({ spawn: mocks.spawn }));
vi.mock('node:net', () => ({
  createServer: () => {
    const server = Object.assign(new EventEmitter(), {
      listen: (options: { port: number }, done: () => void) => {
        mocks.listen(options);
        if (options.port === 3900 && mocks.bindError) {
          queueMicrotask(() =>
            server.emit(
              'error',
              Object.assign(new Error('bind failed'), { code: mocks.bindError }),
            ),
          );
        } else queueMicrotask(done);
        return server;
      },
      address: () => ({ port: 49152 }),
      close: (done: () => void) => {
        mocks.close();
        done();
      },
    });
    return server;
  },
}));
vi.mock('./runtime-project', () => ({
  runtimeReady: async () => true,
  runtimeDependenciesReady: async () => true,
  stageRuntimeSources: async () => {},
  runtimePython: () => '/runtime/python',
}));
import { BackendSupervisor } from './backend';
import { availableBackendPort } from './backend-port';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  mocks.bindError = 'EACCES';
});

it.each([false, true])(
  'recovers a denied default and retries it on restart (existing default backend: %s)',
  async (existingDefault) => {
    vi.stubEnv('OMNIVOICE_PORT', '');
    vi.stubEnv('OMNIVOICE_BACKEND_CMD', '');
    vi.stubEnv('VOICESTUDIO_SKIP_BACKEND', '');
    let runningPort = 0;
    const child = Object.assign(new EventEmitter(), {
      stdin: null,
      stdout: null,
      stderr: null,
      stdio: [],
    });
    mocks.spawn.mockImplementation((_command: string, args: string[]) => {
      const port = Number(args.at(-1));
      // Replay the reported bind denial: this port cannot host a healthy backend.
      runningPort = port === 3900 ? 0 : port;
      return child;
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (!runningPort || !url.startsWith(`http://127.0.0.1:${runningPort}/`))
          throw new Error('unreachable');
        return new Response(JSON.stringify({ status: 'ok', version: 'test' }));
      }),
    );
    const supervisor = new BackendSupervisor();
    try {
      await supervisor.start();
      expect(runningPort).toBe(49152);
      await vi.waitFor(() => expect(supervisor.status.stage).toBe('ready'));
      expect(supervisor.status.baseUrl).toBe('http://127.0.0.1:49152');
      expect(mocks.spawn.mock.calls[0][2].env.OMNIVOICE_PORT).toBe('49152');
      (supervisor as unknown as { child: null }).child = null;
      await supervisor.shutdown();
      runningPort = existingDefault ? 3900 : 0;
      mocks.bindError = null;
      mocks.listen.mockClear();
      mocks.spawn.mockImplementation((_command: string, args: string[]) => {
        runningPort = Number(args.at(-1));
        return child;
      });
      await supervisor.start();
      expect(runningPort).toBe(3900);
      await vi.waitFor(() => expect(supervisor.status.stage).toBe('ready'));
      expect(supervisor.baseUrl).toBe('http://127.0.0.1:3900');
      expect(mocks.spawn).toHaveBeenCalledTimes(existingDefault ? 1 : 2);
      if (existingDefault) expect(mocks.listen).not.toHaveBeenCalled();
      else
        expect(mocks.listen).toHaveBeenCalledExactlyOnceWith({
          host: '127.0.0.1',
          port: 3900,
          exclusive: true,
        });
    } finally {
      // Detach the test child before normal shutdown (no real process was spawned).
      (supervisor as unknown as { child: null }).child = null;
      await supervisor.shutdown();
    }
  },
);

it.each([null, 'EADDRINUSE'])(
  'preserves the preferred port for %s (including replacement attachment)',
  async (error) => {
    mocks.bindError = error;
    expect(await availableBackendPort(3900)).toBe(3900);
    expect(mocks.listen).toHaveBeenCalledExactlyOnceWith({
      host: '127.0.0.1',
      port: 3900,
      exclusive: true,
    });
    expect(mocks.close).toHaveBeenCalledTimes(error ? 0 : 1);
  },
);

it('does not hide unrelated bind failures', async () => {
  mocks.bindError = 'EMFILE';
  await expect(availableBackendPort(3900)).rejects.toMatchObject({ code: 'EMFILE' });
  expect(mocks.listen).toHaveBeenCalledTimes(1);
});

it.each(['explicit port', 'custom command', 'external backend', 'healthy backend'])(
  'never changes the port for an %s',
  async (kind) => {
    vi.stubEnv('OMNIVOICE_PORT', kind === 'explicit port' ? '3900' : '');
    vi.stubEnv('OMNIVOICE_BACKEND_CMD', kind === 'custom command' ? '["custom-python"]' : '');
    vi.stubEnv('VOICESTUDIO_SKIP_BACKEND', kind === 'external backend' ? '1' : '');
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        if (kind !== 'healthy backend') throw new Error('unreachable');
        return new Response(JSON.stringify({ status: 'ok', version: 'test' }));
      }),
    );
    mocks.spawn.mockReturnValue(
      Object.assign(new EventEmitter(), { stdin: null, stdout: null, stderr: null, stdio: [] }),
    );
    const supervisor = new BackendSupervisor();
    try {
      await supervisor.start();
      expect(supervisor.port).toBe(3900);
      expect(mocks.listen).not.toHaveBeenCalled();
    } finally {
      (supervisor as unknown as { child: null }).child = null;
      await supervisor.shutdown();
    }
  },
);
