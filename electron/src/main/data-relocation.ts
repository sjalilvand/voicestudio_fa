import {
  cp,
  chmod,
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  readlink,
  realpath,
  rmdir,
  rm,
  statfs,
  stat,
  symlink,
  writeFile,
} from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { pipeline } from 'node:stream/promises';
import { homedir } from 'node:os';
import { basename, dirname, isAbsolute, join, parse, relative, resolve, sep } from 'node:path';
import { DIRECTORY_RENAME, renameWithRetry } from './rename-retry';

const DATA_KEY = 'OMNIVOICE_DATA_DIR';
const MOVE_RESERVE_BYTES = 64 * 1024 * 1024;

interface ManifestEntry {
  path: string;
  kind: 'file' | 'directory' | 'link';
  size: number;
  link?: string;
}

export interface DataRelocationPlan {
  source: string;
  target: string;
  size_bytes: number;
  file_count: number;
}

export interface PreparedDataRelocation extends DataRelocationPlan {
  removeSource(): Promise<void>;
  rollback(): Promise<void>;
}

export interface DataRelocationResult {
  path: string;
  size_bytes: number;
  file_count: number;
  removed_source: boolean;
}

export interface DataRelocationRuntime {
  stop(): Promise<void>;
  start(): Promise<void>;
  verify(target: string): Promise<boolean>;
  progress(stage: string): void;
  environmentPath?: string;
}

function normalized(path: string): string {
  const value = resolve(path);
  return process.platform === 'win32' ? value.toLocaleLowerCase('en-US') : value;
}

function contains(parent: string, child: string): boolean {
  const rel = relative(normalized(parent), normalized(child));
  // A name such as '..models' is a child; only a complete '..' component escapes.
  return rel === '' || (rel !== '..' && !rel.startsWith(`..${sep}`) && !isAbsolute(rel));
}

function safeDestination(path: string): boolean {
  if (!isAbsolute(path) || dirname(path) === path || /[\0\r\n]/.test(path)) return false;
  if (normalized(path) === normalized(homedir())) return false;
  const root = parse(path).root;
  // Any single directory under the volume root is a valid destination;
  // dirname(path) === path above already refuses the root itself.
  return (
    path
      .slice(root.length)
      .split(/[\\/]+/)
      .filter(Boolean).length >= 1
  );
}

async function canonicalDestination(path: string): Promise<string> {
  try {
    return await realpath(path);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    return join(await realpath(dirname(path)), basename(path));
  }
}

async function manifest(root: string, ignoredRootEntry?: string): Promise<ManifestEntry[]> {
  const output: ManifestEntry[] = [];
  const visit = async (absolute: string, path: string): Promise<void> => {
    const info = await lstat(absolute);
    if (info.isSymbolicLink()) {
      output.push({ path, kind: 'link', size: 0, link: await readlink(absolute) });
      return;
    }
    if (info.isDirectory()) {
      output.push({ path, kind: 'directory', size: 0 });
      const children = await readdir(absolute);
      children.sort();
      for (const child of children) {
        if (path === '' && child === ignoredRootEntry) continue;
        await visit(join(absolute, child), join(path, child));
      }
      return;
    }
    if (!info.isFile()) throw new Error('unsupported_entry');
    output.push({ path, kind: 'file', size: info.size });
  };
  await visit(root, '');
  return output;
}

function manifestBytes(entries: ManifestEntry[]): number {
  return entries.reduce((total, entry) => total + entry.size, 0);
}

async function targetIsEmpty(path: string): Promise<boolean> {
  try {
    const info = await lstat(path);
    return info.isDirectory() && !info.isSymbolicLink() && (await readdir(path)).length === 0;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return true;
    throw error;
  }
}

export async function inspectDataRelocation(
  source: string,
  target: string,
): Promise<DataRelocationPlan> {
  if (!isAbsolute(source) || !safeDestination(target)) throw new Error('unsafe_path');
  const canonicalSource = await realpath(source);
  const canonicalTarget = await canonicalDestination(target);
  if (contains(canonicalSource, canonicalTarget) || contains(canonicalTarget, canonicalSource)) {
    throw new Error('nested_path');
  }
  const sourceInfo = await lstat(canonicalSource);
  if (!sourceInfo.isDirectory() || sourceInfo.isSymbolicLink()) throw new Error('invalid_source');
  if (!(await targetIsEmpty(canonicalTarget))) throw new Error('target_not_empty');
  const entries = await manifest(canonicalSource);
  const size = manifestBytes(entries);
  const capacityPath = await lstat(canonicalTarget).then(
    () => canonicalTarget,
    (error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error;
      return dirname(canonicalTarget);
    },
  );
  const capacity = await statfs(capacityPath);
  const available = Number(capacity.bavail) * Number(capacity.bsize);
  if (available < size + MOVE_RESERVE_BYTES) throw new Error('insufficient_space');
  return {
    source: canonicalSource,
    target: canonicalTarget,
    size_bytes: size,
    file_count: entries.filter((entry) => entry.kind !== 'directory').length,
  };
}

interface OwnedEntry {
  path: string;
  kind: ManifestEntry['kind'];
  dev: bigint;
  ino: bigint;
  mode?: number;
}

// Existing folders may be mount points, or have an unwritable parent. Keep the
// folder itself and reserve each child exclusively: a POSIX rename can overwrite a
// concurrent file on POSIX. Copy once, then verify before starting the backend.
async function prepareExistingDestination(
  plan: DataRelocationPlan,
  sourceManifest: ManifestEntry[],
): Promise<PreparedDataRelocation> {
  const staging = join(plan.target, `.voicestudio-moving-${randomUUID()}`);
  await mkdir(staging, { recursive: false });
  const owned: OwnedEntry[] = [];
  const ownedDirectories = new Map<string, OwnedEntry>();
  const remember = async (
    path: string,
    kind: ManifestEntry['kind'],
    mode?: number,
  ): Promise<void> => {
    const { dev, ino } = await lstat(join(plan.target, path), { bigint: true });
    const entry = { path, kind, dev, ino, mode };
    owned.push(entry);
    if (kind === 'directory') ownedDirectories.set(path, entry);
  };
  const stillOwned = async (entry: OwnedEntry): Promise<boolean> => {
    try {
      const info = await lstat(join(plan.target, entry.path), { bigint: true });
      return info.dev === entry.dev && info.ino === entry.ino;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
      throw error;
    }
  };
  const ownsPath = async (entry: OwnedEntry): Promise<boolean> => {
    for (let parent = dirname(entry.path); parent !== '.'; parent = dirname(parent)) {
      const directory = ownedDirectories.get(parent);
      if (directory && !(await stillOwned(directory))) return false;
    }
    return stillOwned(entry);
  };
  const directoryModes = async (writable: boolean): Promise<void> => {
    const directories = [...ownedDirectories.values()];
    // Open parents before their children, restore children before parents.
    if (!writable) directories.reverse();
    for (const entry of directories) {
      if (await ownsPath(entry)) {
        await chmod(join(plan.target, entry.path), writable ? entry.mode! | 0o700 : entry.mode!);
      }
    }
  };
  const rollback = async (): Promise<void> => {
    // Never follow a replaced parent, delete recursively, or remove unrelated
    // files added while copying / verifying the new backend.
    try {
      await directoryModes(true);
      for (const entry of [...owned].reverse()) {
        if (!(await ownsPath(entry))) continue;
        if (entry.kind === 'directory') {
          await rmdir(join(plan.target, entry.path)).catch((error: NodeJS.ErrnoException) => {
            if (!['ENOENT', 'ENOTEMPTY', 'EEXIST'].includes(error.code || '')) throw error;
          });
        } else {
          await rm(join(plan.target, entry.path), { force: true });
        }
      }
    } finally {
      // A concurrent addition keeps its parent alive; do not leave that folder
      // with the temporary write permission used for cleanup.
      await directoryModes(false);
    }
  };
  try {
    // A small in-target transaction record; model weights are never copied a
    // second time, even on filesystems without hard links (such as exFAT).
    await writeFile(join(staging, 'manifest.json'), JSON.stringify(sourceManifest), { flag: 'wx' });
    for (const entry of sourceManifest) {
      if (!entry.path) continue;
      const destination = join(plan.target, entry.path);
      const original = join(plan.source, entry.path);
      if (entry.kind === 'directory') {
        const mode = (await lstat(original)).mode & 0o7777;
        await mkdir(destination, { recursive: false, mode: mode | 0o700 });
        await remember(entry.path, entry.kind, mode);
      } else if (entry.kind === 'link') {
        const directoryLink = await stat(original).then(
          (info) => info.isDirectory(),
          () => false,
        );
        await symlink(entry.link!, destination, directoryLink ? 'dir' : 'file');
        await remember(entry.path, entry.kind);
      } else {
        const info = await lstat(original);
        const output = await open(destination, 'wx', info.mode);
        try {
          const { dev, ino } = await output.stat({ bigint: true });
          owned.push({ path: entry.path, kind: entry.kind, dev, ino });
          await output.chmod(info.mode);
          await pipeline(createReadStream(original), output.createWriteStream());
        } finally {
          await output.close();
        }
      }
    }
    if (
      JSON.stringify(await manifest(plan.target, basename(staging))) !==
      JSON.stringify(sourceManifest)
    ) {
      throw new Error('verification_failed');
    }
    await directoryModes(false);
    await rm(staging, { recursive: true, force: true });
  } catch (error) {
    await rollback().catch(() => undefined);
    await rm(staging, { recursive: true, force: true }).catch(() => undefined);
    throw error;
  }
  return {
    ...plan,
    removeSource: () => rm(plan.source, { recursive: true, force: false }),
    rollback,
  };
}

export async function prepareDataRelocation(
  source: string,
  target: string,
): Promise<PreparedDataRelocation> {
  const plan = await inspectDataRelocation(source, target);
  const sourceManifest = await manifest(plan.source);
  const existing = await lstat(plan.target).then(
    () => true,
    (error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error;
      return false;
    },
  );
  if (existing) return prepareExistingDestination(plan, sourceManifest);
  const parent = dirname(plan.target);
  const staging = join(parent, `.${basename(plan.target)}.voicestudio-moving-${randomUUID()}`);
  await mkdir(staging, { recursive: false });
  try {
    for (const entry of await readdir(plan.source)) {
      await cp(join(plan.source, entry), join(staging, entry), {
        recursive: true,
        errorOnExist: true,
        force: false,
        verbatimSymlinks: true,
      });
    }
    const copiedManifest = await manifest(staging);
    if (JSON.stringify(copiedManifest) !== JSON.stringify(sourceManifest)) {
      throw new Error('verification_failed');
    }
    try {
      // rm() rejects directories without `recursive`; rmdir removes only an
      // empty one and refuses (ENOTEMPTY) if content appeared since inspection.
      await rmdir(plan.target);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    }
    await renameWithRetry(staging, plan.target, DIRECTORY_RENAME);
  } catch (error) {
    await rm(staging, { recursive: true, force: true }).catch(() => undefined);
    throw error;
  }
  return {
    ...plan,
    removeSource: () => rm(plan.source, { recursive: true, force: false }),
    rollback: () => rm(plan.target, { recursive: true, force: true }),
  };
}

/**
 * Leave the old voices root on record in the moved longform cache (#2279).
 * Chapters rendered by builds before the portable cache key are keyed by the
 * reference audio's absolute path under the OLD data dir; the backend probes
 * every root listed in `voices_roots.json` for them. It records its own root
 * at startup, and this covers the canonical spelling of the source the move
 * came from. Best-effort: no cache means nothing legacy to find, and a failed
 * write never fails the move.
 */
export async function recordPreviousVoicesRoot(source: string, target: string): Promise<void> {
  const cacheDir = join(target, 'outputs', 'longform_cache');
  try {
    if (!(await lstat(cacheDir)).isDirectory()) return;
  } catch {
    return;
  }
  const file = join(cacheDir, 'voices_roots.json');
  let seen: string[] = [];
  try {
    const parsed: unknown = JSON.parse(await readFile(file, 'utf8'));
    if (Array.isArray(parsed)) {
      seen = parsed.filter((root): root is string => typeof root === 'string' && root.length > 0);
    }
  } catch {
    seen = [];
  }
  const previous = join(source, 'voices');
  if (seen.includes(previous)) return;
  const temporary = `${file}.${randomUUID()}.tmp`;
  const handle = await open(temporary, 'w');
  try {
    await handle.writeFile(JSON.stringify([previous, ...seen].slice(0, 8)));
    await handle.sync();
  } finally {
    await handle.close();
  }
  await renameWithRetry(temporary, file);
  await syncDirectory(cacheDir);
}

// Persist a rename into `dir` (POSIX). Windows has no directory handle to
// fsync and journals renames itself; failure is best-effort, like the move.
async function syncDirectory(dir: string): Promise<void> {
  if (process.platform === 'win32') return;
  try {
    const handle = await open(dir, 'r');
    try {
      await handle.sync();
    } finally {
      await handle.close();
    }
  } catch {
    // The index is advisory; a lost entry only costs one re-render.
  }
}

export function userEnvironmentPath(): string {
  return process.env.OMNIVOICE_ENV_FILE || join(homedir(), '.config', 'omnivoice', 'env');
}

export async function readDataDirectorySetting(
  path = userEnvironmentPath(),
): Promise<string | null> {
  let text = '';
  try {
    text = await readFile(path, 'utf8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
  }
  const prefix = `${DATA_KEY}=`;
  const line = text.split(/\r?\n/).find((value) => value.startsWith(prefix));
  if (!line) return null;
  const value = line.slice(prefix.length);
  if (value.startsWith("'") && value.endsWith("'")) {
    return value.slice(1, -1).replace(/\\(['\\])/g, '$1');
  }
  return value;
}

export async function writeDataDirectorySetting(
  value: string | null,
  path = userEnvironmentPath(),
): Promise<void> {
  let text = '';
  try {
    text = await readFile(path, 'utf8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
  }
  const prefix = `${DATA_KEY}=`;
  const lines = text.split(/\r?\n/).filter((line) => line && !line.startsWith(prefix));
  if (value) {
    if (/[\0\r\n]/.test(value)) throw new Error('unsafe_path');
    const encoded = value.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    lines.push(`${DATA_KEY}='${encoded}'`);
  }
  const body = lines.length ? `${lines.join('\n')}\n` : '';
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, body, { encoding: 'utf8', mode: 0o600 });
  try {
    await renameWithRetry(temporary, path);
  } catch (error) {
    await rm(temporary, { force: true }).catch(() => undefined);
    throw error;
  }
}

export async function relocateDataDirectory(
  source: string,
  target: string,
  runtime: DataRelocationRuntime,
): Promise<DataRelocationResult> {
  let prepared: PreparedDataRelocation | null = null;
  let previousSetting: string | null = null;
  let settingChanged = false;
  let stopped = false;
  let started = false;
  try {
    runtime.progress('stopping');
    await runtime.stop();
    stopped = true;
    runtime.progress('copying');
    prepared = await prepareDataRelocation(source, target);
    previousSetting = await readDataDirectorySetting(runtime.environmentPath);
    runtime.progress('switching');
    await writeDataDirectorySetting(target, runtime.environmentPath);
    settingChanged = true;
    runtime.progress('restarting');
    await runtime.start();
    started = true;
    if (!(await runtime.verify(target))) throw new Error('backend_verification_failed');
    // Advisory cache writes replace their inode; defer them until activation so
    // a failed move can identify every copied entry during rollback.
    await recordPreviousVoicesRoot(prepared.source, prepared.target).catch(() => undefined);
    runtime.progress('cleaning');
    let removedSource = true;
    try {
      await prepared.removeSource();
    } catch {
      removedSource = false;
    }
    runtime.progress('done');
    return {
      path: target,
      size_bytes: prepared.size_bytes,
      file_count: prepared.file_count,
      removed_source: removedSource,
    };
  } catch (error) {
    runtime.progress('rolling_back');
    if (started) await runtime.stop().catch(() => undefined);
    if (settingChanged) {
      await writeDataDirectorySetting(previousSetting, runtime.environmentPath).catch(
        () => undefined,
      );
    }
    if (prepared) await prepared.rollback().catch(() => undefined);
    if (stopped) await runtime.start().catch(() => undefined);
    throw error;
  }
}
