import { describe, expect, it, vi } from 'vitest';
import { AccountApi } from './account-api';
import { CloudActivity, type FetchImpl } from './cloud-activity';
import { cloudOrigins, resolveCloudEnvironment } from './cloud-config';

const env = resolveCloudEnvironment({ packaged: true });
const account = {
  user_id: 'Us3nM8qWe2RtY6uI',
  email: 'ana@example.com',
  email_verified: true,
  display_name: 'Ana',
  avatar_url: null,
  personal_organization_id: 'Or5tG7hJ9kL1zX3c',
  organizations: [
    { id: 'Or5tG7hJ9kL1zX3c', slug: 'ana', display_name: 'Ana', role: 'owner', kind: 'personal' },
  ],
};
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
function setup(responses: Response[]) {
  const fetchImpl = vi.fn<FetchImpl>(async () => responses.shift()!);
  const session = {
    getAccessToken: vi.fn(async () => ({ access_token: 'tok', expires_at: 9e15 })),
    invalidateAccessToken: vi.fn(),
    endSession: vi.fn(),
  };
  const activity = new CloudActivity({
    isAllowed: () => true,
    origins: cloudOrigins(env),
    fetchImpl,
  });
  return { api: new AccountApi(env, session as never, activity), fetchImpl, session };
}

it('maps the account to the renderer-safe profile', async () => {
  const { api, fetchImpl } = setup([json(account)]);
  expect(await api.get()).toEqual({
    email: 'ana@example.com',
    displayName: 'Ana',
    avatarUrl: null,
    personalOrganizationId: 'Or5tG7hJ9kL1zX3c',
    organizations: [
      { id: 'Or5tG7hJ9kL1zX3c', slug: 'ana', displayName: 'Ana', role: 'owner', kind: 'personal' },
    ],
  });
  expect(fetchImpl.mock.calls[0][0]).toBe('https://appapi.voicestudio.sh/v1/account');
  expect((fetchImpl.mock.calls[0][1] as RequestInit).headers).toMatchObject({
    authorization: 'Bearer tok',
  });
});

it('refreshes once on 401, then signs out on a second 401', async () => {
  const { api, session } = setup([json({}, 401), json({}, 401)]);
  expect(await api.get()).toBeNull();
  expect(session.invalidateAccessToken).toHaveBeenCalledOnce();
  expect(session.endSession).toHaveBeenCalledWith('signed_out_expired');
});

it('PATCH reuses its Idempotency-Key when retrying after 401', async () => {
  const { api, fetchImpl } = setup([json({}, 401), json(account)]);
  await api.patch({ display_name: 'Ana B' });
  const keys = fetchImpl.mock.calls.map(
    (c) => ((c[1] as RequestInit).headers as Record<string, string>)['idempotency-key'],
  );
  expect(keys[0]).toMatch(/^[0-9a-f]{32}$/);
  expect(keys[1]).toBe(keys[0]);
});

it('returns null without a request when signed out', async () => {
  const { api, fetchImpl, session } = setup([]);
  session.getAccessToken.mockResolvedValueOnce(null as never);
  expect(await api.get()).toBeNull();
  expect(fetchImpl).not.toHaveBeenCalled();
});

describe('profile photo', () => {
  const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3]);
  function photoApi(response: () => Response) {
    const fetchImpl = vi.fn<FetchImpl>(async () => response());
    const session = {
      getAccessToken: vi.fn(),
      invalidateAccessToken: vi.fn(),
      endSession: vi.fn(),
    };
    const activity = new CloudActivity({
      isAllowed: () => true,
      origins: cloudOrigins(env),
      fetchImpl,
    });
    return { api: new AccountApi(env, session as never, activity), fetchImpl };
  }
  const image = () => new Response(png, { headers: { 'content-type': 'image/png' } });

  it('downloads the photo once as a data URL the renderer can show', async () => {
    const { api, fetchImpl } = photoApi(image);
    const first = await api.avatar(
      'https://app-s3.voicestudio.sh/avatars/u1.png?X-Amz-Signature=a',
    );
    const again = await api.avatar(
      'https://app-s3.voicestudio.sh/avatars/u1.png?X-Amz-Signature=b',
    );
    expect(first).toBe(`data:image/png;base64,${Buffer.from(png).toString('base64')}`);
    expect(again).toBe(first);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('refuses anything that is not a small image', async () => {
    expect(
      await photoApi(
        () => new Response('<svg/>', { headers: { 'content-type': 'image/svg+xml' } }),
      ).api.avatar('https://x.example/a'),
    ).toBeNull();
    expect(
      await photoApi(
        () => new Response('hi', { headers: { 'content-type': 'text/html' } }),
      ).api.avatar('https://x.example/a'),
    ).toBeNull();
    const big = new Uint8Array(2 * 1024 * 1024 + 1);
    expect(
      await photoApi(
        () => new Response(big, { headers: { 'content-type': 'image/jpeg' } }),
      ).api.avatar('https://x.example/a'),
    ).toBeNull();
    expect(await photoApi(image).api.avatar('http://x.example/a.png')).toBeNull();
    expect(await photoApi(image).api.avatar(null)).toBeNull();
  });
});

it('reads the plan, storage and what the plan includes for an Organization', async () => {
  const entitlements = {
    organization_id: 'Or5tG7hJ9kL1zX3c',
    plan: { code: 'pro', name: 'Pro', source: 'subscription' },
    values: [
      { key: 'storage.bytes', type: 'bytes', value: 1073741824, sources: [] },
      { key: 'sync.settings', type: 'flag', value: 1, sources: [] },
      { key: 'pro.desktop', type: 'flag', value: 0, sources: [] },
    ],
    storage: { limit_bytes: 1073741824, used_bytes: 734003, reserved_bytes: 0 },
    grants: [],
    products: [],
    can_manage: true,
    resolved_at: '2026-10-16T09:00:00Z',
  };
  const { api, fetchImpl } = setup([json(entitlements)]);
  expect(await api.entitlements('Or5tG7hJ9kL1zX3c')).toEqual({
    planCode: 'pro',
    planName: 'Pro',
    storageUsedBytes: 734003,
    storageLimitBytes: 1073741824,
    settingsSync: true,
    proDesktop: false,
  });
  expect(fetchImpl.mock.calls[0][0]).toBe(
    'https://appapi.voicestudio.sh/v1/account/organizations/Or5tG7hJ9kL1zX3c/entitlements',
  );
});

it('refuses an Organization ID that could change the request path', async () => {
  const { api, fetchImpl } = setup([]);
  expect(await api.entitlements('../admin')).toBeNull();
  expect(fetchImpl).not.toHaveBeenCalled();
});
