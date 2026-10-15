import { expect, it, vi } from 'vitest';
import { AccountApi } from './account-api';
import { CloudActivity, type FetchImpl } from './cloud-activity';
import { cloudOrigins, resolveCloudEnvironment } from './cloud-config';

const env = resolveCloudEnvironment({ packaged: true });
const account = {
  user_id: 'Us3nM8qWe2RtY6uI', email: 'ana@example.com', email_verified: true, display_name: 'Ana',
  avatar_url: null, personal_organization_id: 'Or5tG7hJ9kL1zX3c',
  organizations: [{ id: 'Or5tG7hJ9kL1zX3c', slug: 'ana', display_name: 'Ana', role: 'owner', kind: 'personal' }],
};
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
function setup(responses: Response[]) {
  const fetchImpl = vi.fn<FetchImpl>(async () => responses.shift()!);
  const session = {
    getAccessToken: vi.fn(async () => ({ access_token: 'tok', expires_at: 9e15 })),
    invalidateAccessToken: vi.fn(),
    endSession: vi.fn(),
  };
  const activity = new CloudActivity({ isAllowed: () => true, origins: cloudOrigins(env), fetchImpl });
  return { api: new AccountApi(env, session as never, activity), fetchImpl, session };
}

it('maps the account to the renderer-safe profile', async () => {
  const { api, fetchImpl } = setup([json(account)]);
  expect(await api.get()).toEqual({
    email: 'ana@example.com', displayName: 'Ana', avatarUrl: null,
    organizations: [{ id: 'Or5tG7hJ9kL1zX3c', slug: 'ana', displayName: 'Ana', role: 'owner', kind: 'personal' }],
  });
  expect(fetchImpl.mock.calls[0][0]).toBe('https://appapi.voicestudio.sh/v1/account');
  expect((fetchImpl.mock.calls[0][1] as RequestInit).headers).toMatchObject({ authorization: 'Bearer tok' });
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
  const keys = fetchImpl.mock.calls.map((c) => ((c[1] as RequestInit).headers as Record<string, string>)['idempotency-key']);
  expect(keys[0]).toMatch(/^[0-9a-f]{32}$/);
  expect(keys[1]).toBe(keys[0]);
});

it('returns null without a request when signed out', async () => {
  const { api, fetchImpl, session } = setup([]);
  session.getAccessToken.mockResolvedValueOnce(null as never);
  expect(await api.get()).toBeNull();
  expect(fetchImpl).not.toHaveBeenCalled();
});
