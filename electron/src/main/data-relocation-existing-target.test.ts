// @vitest-environment node
import { existsSync } from 'node:fs';
import {
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { afterEach, expect, it, vi } from 'vitest';
import {
  prepareDataRelocation,
  inspectDataRelocation,
  readDataDirectorySetting,
  relocateDataDirectory,
} from './data-relocation';

const constraints = vi.hoisted(() => ({
  target: '',
  parent: '',
  checkCapacity: false,
  beforeOpen: null as ((path: string) => Promise<void>) | null,
  collisionDirectory: '',
  failRead: '',
  unsupportedPath: '',
  largeIdentityPath: '',
  identityVersion: 0,
}));
vi.mock('node:fs/promises', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs/promises')>();
  return {
    ...actual,
    mkdir: async (...args: Parameters<typeof actual.mkdir>) => {
      if (constraints.parent && dirname(String(args[0])) === constraints.parent) {
        throw Object.assign(new Error('parent is not writable'), { code: 'EACCES' });
      }
      if (String(args[0]) === constraints.collisionDirectory) {
        await actual.mkdir(...args);
        await actual.writeFile(join(String(args[0]), 'concurrent.txt'), 'keep');
      }
      return actual.mkdir(...args);
    },
    rmdir: async (...args: Parameters<typeof actual.rmdir>) => {
      if (String(args[0]) === constraints.target) {
        throw Object.assign(new Error('destination is a mount point'), { code: 'EBUSY' });
      }
      return actual.rmdir(...args);
    },
    lstat: async (...args: Parameters<typeof actual.lstat>) => {
      const info = await actual.lstat(...args);
      if (String(args[0]) === constraints.largeIdentityPath) {
        const ino = 9007199254740992n + BigInt(constraints.identityVersion);
        return Object.assign(Object.create(info), {
          ino: typeof info.ino === 'bigint' ? ino : Number(ino),
        });
      }
      return String(args[0]) === constraints.unsupportedPath
        ? Object.assign(Object.create(info), { isFile: () => false })
        : info;
    },
    open: async (...args: Parameters<typeof actual.open>) => {
      await constraints.beforeOpen?.(String(args[0]));
      return actual.open(...args);
    },
    statfs: async (...args: Parameters<typeof actual.statfs>) => {
      if (constraints.checkCapacity) {
        return { bavail: String(args[0]) === constraints.target ? 1024 ** 3 : 0, bsize: 1 };
      }
      return actual.statfs(...args);
    },
  };
});

vi.mock('node:fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs')>();
  const { Readable } = await import('node:stream');
  return {
    ...actual,
    createReadStream: (...args: Parameters<typeof actual.createReadStream>) => {
      if (String(args[0]) === constraints.failRead) {
        return Readable.from(
          (async function* () {
            yield 'partial';
            throw Object.assign(new Error('read interrupted'), { code: 'EIO' });
          })(),
        );
      }
      return actual.createReadStream(...args);
    },
  };
});

const created: string[] = [];
const readOnlyDirectories: string[] = [];
afterEach(async () => {
  await Promise.all(
    readOnlyDirectories.splice(0).map((path) => chmod(path, 0o755).catch(() => undefined)),
  );
  constraints.target = constraints.parent = '';
  constraints.checkCapacity = false;
  constraints.beforeOpen = null;
  constraints.largeIdentityPath = '';
  constraints.identityVersion = 0;
  constraints.collisionDirectory = constraints.failRead = constraints.unsupportedPath = '';
  await Promise.all(created.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

async function fixture() {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'VoiceStudio-existing-target-')));
  created.push(root);
  const source = join(root, 'old', 'data');
  const target = join(root, 'mounted', 'data');
  await mkdir(join(source, 'voices'), { recursive: true });
  await mkdir(target, { recursive: true });
  await writeFile(join(source, 'voices', 'sample.wav'), 'voice');
  await writeFile(join(source, 'omnivoice.db'), 'database');
  return { root, source, target };
}

it.each([true, false])(
  'preserves a writable mounted destination beneath a protected parent (activation: %s)',
  async (activate) => {
    const { root, source, target } = await fixture();
    const environmentPath = join(root, 'env');
    await writeFile(environmentPath, `OMNIVOICE_DATA_DIR=${source}\n`);
    const inode = (await lstat(target)).ino;
    constraints.target = target;
    constraints.parent = dirname(target);
    const move = relocateDataDirectory(source, target, {
      environmentPath,
      stop: async () => undefined,
      start: async () => undefined,
      verify: async () => {
        expect(await readFile(join(target, 'voices', 'sample.wav'), 'utf8')).toBe('voice');
        await writeFile(join(target, 'personal.txt'), 'keep');
        return activate;
      },
      progress: () => undefined,
    });
    if (activate) await expect(move).resolves.toMatchObject({ removed_source: true });
    else await expect(move).rejects.toThrow('backend_verification_failed');
    expect((await lstat(target)).ino).toBe(inode);
    expect(await readFile(join(target, 'personal.txt'), 'utf8')).toBe('keep');
    expect(existsSync(source)).toBe(!activate);
    expect(await readDataDirectorySetting(environmentPath)).toBe(activate ? target : source);
    if (!activate) expect(await readdir(target)).toEqual(['personal.txt']);
  },
);

it('checks capacity on the selected existing filesystem rather than its parent', async () => {
  const { source, target } = await fixture();
  constraints.target = target;
  constraints.checkCapacity = true;
  await expect(inspectDataRelocation(source, target)).resolves.toMatchObject({ target });
});

it('refuses a concurrently created file and rolls back only its earlier entries', async () => {
  const { source, target } = await fixture();
  constraints.beforeOpen = async (path) => {
    if (path === join(target, 'voices', 'sample.wav')) await writeFile(path, 'concurrent');
  };
  await expect(prepareDataRelocation(source, target)).rejects.toMatchObject({ code: 'EEXIST' });
  expect(await readFile(join(target, 'voices', 'sample.wav'), 'utf8')).toBe('concurrent');
  expect(await readdir(target)).toEqual(['voices']);
  expect(await readFile(join(source, 'omnivoice.db'), 'utf8')).toBe('database');
});

it('refuses a concurrently created directory without merging into it', async () => {
  const { source, target } = await fixture();
  constraints.collisionDirectory = join(target, 'voices');
  await expect(prepareDataRelocation(source, target)).rejects.toMatchObject({ code: 'EEXIST' });
  expect(await readdir(target)).toEqual(['voices']);
  expect(await readdir(join(target, 'voices'))).toEqual(['concurrent.txt']);
});

it('cleans a partial exclusive copy after a read failure and keeps the source', async () => {
  const { source, target } = await fixture();
  constraints.failRead = join(source, 'voices', 'sample.wav');
  await expect(prepareDataRelocation(source, target)).rejects.toThrow('read interrupted');
  expect(await readdir(target)).toEqual([]);
  expect(await readFile(join(source, 'voices', 'sample.wav'), 'utf8')).toBe('voice');
});

it('rollback keeps replacements and new files inside an owned directory', async () => {
  const { root, source, target } = await fixture();
  const prepared = await prepareDataRelocation(source, target);
  await writeFile(join(target, 'voices', 'concurrent.txt'), 'keep nested');
  const replacement = join(root, 'replacement');
  await writeFile(replacement, 'keep replacement');
  await rename(replacement, join(target, 'omnivoice.db'));
  await prepared.rollback();
  expect(await readdir(target)).toEqual(['omnivoice.db', 'voices']);
  expect(await readFile(join(target, 'omnivoice.db'), 'utf8')).toBe('keep replacement');
  expect(await readdir(join(target, 'voices'))).toEqual(['concurrent.txt']);
  expect(existsSync(source)).toBe(true);
});

it('failed activation rolls back copied longform cache entries before advisory writes', async () => {
  const { root, source, target } = await fixture();
  const cache = join(source, 'outputs', 'longform_cache');
  await mkdir(cache, { recursive: true });
  await writeFile(join(cache, 'voices_roots.json'), JSON.stringify(['/previous/voices']));
  await expect(
    relocateDataDirectory(source, target, {
      environmentPath: join(root, 'env'),
      stop: async () => undefined,
      start: async () => undefined,
      verify: async () => false,
      progress: () => undefined,
    }),
  ).rejects.toThrow('backend_verification_failed');
  expect(await readdir(target)).toEqual([]);
  expect(await readFile(join(cache, 'voices_roots.json'), 'utf8')).toBe(
    JSON.stringify(['/previous/voices']),
  );
});

it('rollback never traverses a directory replaced concurrently', async () => {
  const { root, source, target } = await fixture();
  const prepared = await prepareDataRelocation(source, target);
  await rename(join(target, 'voices'), join(root, 'moved-voices'));
  await mkdir(join(target, 'voices'));
  await writeFile(join(target, 'voices', 'sample.wav'), 'unrelated');
  await prepared.rollback();
  expect(await readdir(target)).toEqual(['voices']);
  expect(await readFile(join(target, 'voices', 'sample.wav'), 'utf8')).toBe('unrelated');
});

it('rejects unsupported source entries rather than silently dropping them', async () => {
  const { source, target } = await fixture();
  constraints.unsupportedPath = join(source, 'voices', 'sample.wav');
  await expect(prepareDataRelocation(source, target)).rejects.toThrow('unsupported_entry');
  expect(await readdir(target)).toEqual([]);
  expect(await readFile(join(source, 'voices', 'sample.wav'), 'utf8')).toBe('voice');
});

// Windows does not enforce POSIX directory modes; root bypasses write checks.
it.skipIf(process.platform === 'win32' || process.getuid?.() === 0)(
  'copies read-only model directories and files, preserves modes, and can roll back',
  async () => {
    const { source, target } = await fixture();
    const sourceVoices = join(source, 'voices');
    const targetVoices = join(target, 'voices');
    readOnlyDirectories.push(sourceVoices, targetVoices);
    await chmod(sourceVoices, 0o555);
    await chmod(join(sourceVoices, 'sample.wav'), 0o444);
    const prepared = await prepareDataRelocation(source, target);
    expect(await readFile(join(targetVoices, 'sample.wav'), 'utf8')).toBe('voice');
    expect((await lstat(targetVoices)).mode & 0o777).toBe(0o555);
    expect((await lstat(join(targetVoices, 'sample.wav'))).mode & 0o777).toBe(0o444);
    await prepared.rollback();
    expect(await readdir(target)).toEqual([]);
    expect((await lstat(sourceVoices)).mode & 0o777).toBe(0o555);
  },
);

it.skipIf(process.platform === 'win32' || process.getuid?.() === 0)(
  'failed activation removes owned files from read-only directories but restores modes on surviving data',
  async () => {
    const { root, source, target } = await fixture();
    const sourceVoices = join(source, 'voices');
    const targetVoices = join(target, 'voices');
    readOnlyDirectories.push(sourceVoices, targetVoices);
    await chmod(sourceVoices, 0o555);
    await expect(
      relocateDataDirectory(source, target, {
        environmentPath: join(root, 'env'),
        stop: async () => undefined,
        start: async () => undefined,
        verify: async () => {
          expect((await lstat(targetVoices)).mode & 0o777).toBe(0o555);
          await chmod(targetVoices, 0o755);
          await writeFile(join(targetVoices, 'concurrent.txt'), 'keep');
          await chmod(targetVoices, 0o555);
          return false;
        },
        progress: () => undefined,
      }),
    ).rejects.toThrow('backend_verification_failed');
    expect(await readdir(target)).toEqual(['voices']);
    expect(await readdir(targetVoices)).toEqual(['concurrent.txt']);
    expect((await lstat(targetVoices)).mode & 0o777).toBe(0o555);
    expect((await lstat(sourceVoices)).mode & 0o777).toBe(0o555);
  },
);

it('does not claim a replacement directory whose 64-bit file ID rounds to the same Number', async () => {
  const { root, source, target } = await fixture();
  const voices = join(target, 'voices');
  constraints.largeIdentityPath = voices;
  const prepared = await prepareDataRelocation(source, target);
  await rename(voices, join(root, 'moved-voices'));
  await mkdir(voices);
  constraints.identityVersion = 1;
  // These distinct filesystem IDs collide if read through numeric Stats.
  expect(Number(9007199254740992n)).toBe(Number(9007199254740993n));
  await prepared.rollback();
  expect(existsSync(voices)).toBe(true);
});

it.skipIf(process.platform === 'win32' || process.getuid?.() === 0)(
  'restores read-only modes on surviving concurrent data after a copy failure',
  async () => {
    const { source, target } = await fixture();
    const sourceVoices = join(source, 'voices');
    const targetVoices = join(target, 'voices');
    readOnlyDirectories.push(sourceVoices, targetVoices);
    await chmod(sourceVoices, 0o555);
    constraints.beforeOpen = async (path) => {
      if (path === join(targetVoices, 'sample.wav')) {
        await writeFile(join(targetVoices, 'concurrent.txt'), 'keep');
        throw Object.assign(new Error('copy interrupted'), { code: 'EIO' });
      }
    };
    await expect(prepareDataRelocation(source, target)).rejects.toThrow('copy interrupted');
    expect(await readdir(targetVoices)).toEqual(['concurrent.txt']);
    expect((await lstat(targetVoices)).mode & 0o777).toBe(0o555);
  },
);
