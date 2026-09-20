import { expect, it } from 'vitest';
import {
  INTEGRATION_CATALOG,
  integrationSlug,
  getIntegrationBySlug,
} from '../../../../../../frontend/src/config/integration-catalog';

it('gives every directory entry one stable route and its actual category', () => {
  const slugs = INTEGRATION_CATALOG.map((entry) => integrationSlug(entry.name));
  expect(new Set(slugs).size).toBe(slugs.length);
  expect(getIntegrationBySlug('n8n')?.category).toBe('automation');
  expect(getIntegrationBySlug('claude-code')?.category).toBe('agents');
});

import { mcpSetup } from './mcp-setup';
it('exports client-specific HTTP configuration for the actual backend and port', () => {
  const claude = mcpSetup('claude-code', 'http://127.0.0.1:3912');
  const cursor = mcpSetup('cursor', 'https://voice.example/backend/');
  expect(claude?.file).toBe('.mcp.json');
  expect(JSON.parse(claude!.text).mcpServers.voicestudio).toEqual({
    type: 'http',
    url: 'http://127.0.0.1:3912/mcp',
    headers: { 'X-VoiceStudio-Client-Id': 'claude-code' },
  });
  expect(cursor?.file).toBe('.cursor/mcp.json');
  expect(JSON.parse(cursor!.text).mcpServers.voicestudio).toEqual({
    url: 'https://voice.example/backend/mcp',
    headers: { 'X-VoiceStudio-Client-Id': 'cursor' },
  });
});
it('never exports credentials, unsafe URLs, or unsupported client configurations', () => {
  for (const url of [
    '',
    'file:///tmp/backend',
    'http://secret:password@localhost:3900',
    'https://host/?key=secret',
    'https://host/#secret',
  ]) {
    expect(mcpSetup('claude-code', url)).toBeNull();
  }
  expect(mcpSetup('constructor', 'http://localhost:3900')).toBeNull();
  expect(mcpSetup('twilio', 'http://localhost:3900')).toBeNull();
});
