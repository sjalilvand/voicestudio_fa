import { randomBytes } from 'node:crypto';
import type { AccountSession } from './account-session';
import type { CloudActivity } from './cloud-activity';
import type { CloudEnvironment } from './cloud-config';

export interface AccountProfile {
  email: string | null;
  displayName: string | null;
  avatarUrl: string | null;
  organizations: Array<{ id: string; slug: string; displayName: string; role: string; kind: string }>;
}

interface RawAccount {
  email?: string | null;
  display_name?: string | null;
  avatar_url?: string | null;
  organizations?: Array<{ id: string; slug: string; display_name: string; role: string; kind: string }>;
}

const toProfile = (a: RawAccount): AccountProfile => ({
  email: a.email ?? null,
  displayName: a.display_name ?? null,
  avatarUrl: a.avatar_url ?? null,
  organizations: (a.organizations ?? []).map((o) => ({
    id: o.id, slug: o.slug, displayName: o.display_name, role: o.role, kind: o.kind,
  })),
});

export class AccountApi {
  constructor(
    private readonly env: CloudEnvironment,
    private readonly session: AccountSession,
    private readonly activity: CloudActivity,
  ) {}

  get(): Promise<AccountProfile | null> {
    return this.call({ method: 'GET' });
  }

  patch(changes: { display_name?: string; theme?: 'system' | 'light' | 'dark'; language?: string }) {
    return this.call({
      method: 'PATCH',
      body: JSON.stringify(changes),
      headers: { 'content-type': 'application/json', 'idempotency-key': randomBytes(16).toString('hex') },
    });
  }

  private async call(init: { method: string; body?: string; headers?: Record<string, string> }) {
    for (let attempt = 0; attempt < 2; attempt++) {
      const token = await this.session.getAccessToken();
      if (!token) return null;
      const res = await this.activity.fetch(this.env.accountApi, {
        ...init,
        headers: { ...init.headers, authorization: `Bearer ${token.access_token}` },
      });
      if (res.status === 401) {
        if (attempt === 0) this.session.invalidateAccessToken();
        continue;
      }
      if (!res.ok) throw new Error(`Account request failed (${res.status})`);
      return toProfile((await res.json()) as RawAccount);
    }
    this.session.endSession('signed_out_expired');
    return null;
  }
}
