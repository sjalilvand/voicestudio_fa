import { describe, expect, it, vi } from 'vitest';
import {
  devElectronPids,
  devInstancePorts,
  replacePreviousDevInstance,
  stopLeftoverDevApps,
  // @ts-expect-error JavaScript launcher has no separate declaration file.
} from '../../scripts/dev.mjs';

describe('bun dev replaces an earlier dev instance', () => {
  it('clears only the dev proxy and renderer ports, never the backend port', () => {
    expect(devInstancePorts({})).toEqual([3903, 3902]);
    expect(
      devInstancePorts({ VOICESTUDIO_UI_PORT: '4100', VOICESTUDIO_ELECTRON_PROXY_PORT: '4200' }),
    ).toEqual([4200, 4100]);
  });

  it('frees the ports, then stops leftover dev apps, unless multiple instances are allowed', async () => {
    const order: string[] = [];
    const clear = vi.fn(async () => void order.push('clear'));
    const stopApps = vi.fn(async () => void order.push('apps'));
    await replacePreviousDevInstance({}, clear, stopApps);
    expect(order).toEqual(['clear', 'apps']);
    await replacePreviousDevInstance(
      { VOICESTUDIO_ALLOW_MULTIPLE_INSTANCES: '1' },
      clear,
      stopApps,
    );
    expect(clear).toHaveBeenCalledTimes(1);
  });

  it('matches only processes running from the dev Electron location', () => {
    const listing = [
      '  101 /repo/electron/node_modules/.cache/voicestudio-electron-dev/x/VoiceStudio.app/Contents/MacOS/Electron .',
      '  102 /Applications/VoiceStudio.app/Contents/MacOS/VoiceStudio',
      '  103 /repo/electron/node_modules/.cache/voicestudio-electron-dev-old/Electron',
      '  104 /usr/bin/node /repo/electron/node_modules/.cache/voicestudio-electron-dev/x',
    ].join('\n');
    expect(
      devElectronPids(
        listing,
        '/repo/electron/node_modules/.cache/voicestudio-electron-dev/',
        false,
      ),
    ).toEqual([101]);
    expect(
      devElectronPids(
        '4 C:\\Repo\\electron\\node_modules\\electron\\dist\\electron.exe\r\n5 C:\\Other\\electron.exe',
        'C:/Repo/electron/node_modules/electron/dist/',
        true,
      ),
    ).toEqual([4]);
  });

  it('asks a leftover dev app to quit and forces it only if it is still there', async () => {
    let running = [7];
    const kill = vi.fn((pid: number, signal: string) => {
      if (signal === 'SIGKILL') running = running.filter((p) => p !== pid);
    });
    await stopLeftoverDevApps({
      location: '/dev/',
      list: () => running.map((pid) => `${pid} /dev/Electron .`).join('\n'),
      kill,
      sleep: async () => {},
      timeoutMs: 1000,
    });
    expect(kill.mock.calls).toEqual([
      [7, 'SIGTERM'],
      [7, 'SIGKILL'],
    ]);

    kill.mockClear();
    running = [8];
    await stopLeftoverDevApps({
      location: '/dev/',
      list: () => running.map((pid) => `${pid} /dev/Electron .`).join('\n'),
      kill: (pid: number, signal: string) => {
        kill(pid, signal);
        running = [];
      },
      sleep: async () => {},
    });
    expect(kill.mock.calls).toEqual([[8, 'SIGTERM']]);
  });
});
