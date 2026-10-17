import { test } from 'node:test';
import assert from 'node:assert/strict';
import { startHealthBackend } from './fake-health-backend.mjs';

const get = (backend, path, init) => fetch(`http://127.0.0.1:${backend.port}${path}`, init);

test('defaults answer /health', async () => {
  const backend = await startHealthBackend();
  try {
    const response = await get(backend, '/health');
    assert.deepEqual(await response.json(), { status: 'ok', version: 'native-smoke' });
  } finally {
    await backend.close();
  }
});

test('override replaces one fixture', async () => {
  const analytics = { available: true, prompted: false, opted_in: false };
  const backend = await startHealthBackend({
    fixtures: { '/api/settings/analytics': analytics },
  });
  try {
    const response = await get(backend, '/api/settings/analytics');
    assert.deepEqual(await response.json(), analytics);
  } finally {
    await backend.close();
  }
});

test('unknown path is 404 and recorded', async () => {
  const backend = await startHealthBackend();
  try {
    const response = await get(backend, '/nope');
    assert.equal(response.status, 404);
    assert.deepEqual(backend.requests.at(-1), {
      method: 'GET',
      path: '/nope',
      status: 404,
      body: '',
    });
  } finally {
    await backend.close();
  }
});

test('POST body is recorded', async () => {
  const backend = await startHealthBackend();
  try {
    await get(backend, '/api/settings/analytics', {
      method: 'POST',
      body: '{"opted_in":false}',
    });
    assert.equal(backend.requests.at(-1).body, '{"opted_in":false}');
  } finally {
    await backend.close();
  }
});
