import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import type { NativeCrashRecord } from '../preload/index.d';

/** Small version-scoped local journal. Read failures must never block startup. */
export class CrashJournal {
  private records: NativeCrashRecord[] = [];
  constructor(
    private path: string,
    private version: string,
  ) {
    try {
      const stored: unknown = JSON.parse(readFileSync(path, 'utf8'));
      if (Array.isArray(stored))
        this.records = stored
          .filter(
            (
              value,
            ): value is Omit<NativeCrashRecord, 'acknowledged'> & {
              acknowledged?: boolean;
            } =>
              value &&
              value.version === version &&
              Number.isFinite(value.timestamp) &&
              Number.isFinite(value.uptimeMs) &&
              Array.isArray(value.logTail) &&
              value.logTail.every((line: unknown) => typeof line === 'string') &&
              (value.exitCode === null || Number.isInteger(value.exitCode)) &&
              (value.signal === null || typeof value.signal === 'string'),
          )
          .map((value) => ({ ...value, acknowledged: value.acknowledged === true }))
          .slice(0, 3);
    } catch {
      /* missing or corrupt journal */
    }
  }
  latest(): NativeCrashRecord | undefined {
    return this.records[0];
  }
  acknowledgeLatest(): NativeCrashRecord | undefined {
    const latest = this.records[0];
    if (!latest || latest.acknowledged) return latest;
    this.records[0] = { ...latest, acknowledged: true };
    this.persist();
    return this.records[0];
  }
  record(
    exitCode: number | null,
    signal: string | null,
    uptimeMs: number,
    logTail: string[],
  ): void {
    // EX_CONFIG is a port collision; Windows debugger termination is not a backend fault.
    if (exitCode === 78 || exitCode === 0x40010004) return;
    this.records.unshift({
      timestamp: Date.now(),
      version: this.version,
      exitCode,
      signal,
      uptimeMs: Math.max(0, uptimeMs),
      logTail: logTail.slice(-40).map((line) => line.slice(-4096)),
      acknowledged: false,
    });
    this.records = this.records.slice(0, 3);
    this.persist();
  }
  private persist(): void {
    try {
      writeFileSync(this.path + '.tmp', JSON.stringify(this.records), {
        encoding: 'utf8',
        mode: 0o600,
      });
      renameSync(this.path + '.tmp', this.path);
    } catch {
      /* retain in memory when storage is unavailable */
    }
  }
}
