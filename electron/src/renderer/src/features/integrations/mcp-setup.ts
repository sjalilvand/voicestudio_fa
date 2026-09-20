const CLIENTS = {
  'claude-code': { file: '.mcp.json', docs: 'https://code.claude.com/docs/en/mcp', type: 'http' },
  cursor: { file: '.cursor/mcp.json', docs: 'https://cursor.com/docs/mcp', type: undefined },
} as const;

/** Export configuration, never credentials or commands that overwrite client files. */
export function mcpSetup(slug: string, baseUrl: string) {
  if (!Object.hasOwn(CLIENTS, slug)) return null;
  const client = CLIENTS[slug as keyof typeof CLIENTS];
  const url = backendEndpoint(baseUrl, '/mcp');
  if (!url) return null;
  return {
    file: client.file,
    docs: client.docs,
    text: JSON.stringify(
      {
        mcpServers: {
          voicestudio: {
            ...(client.type ? { type: client.type } : {}),
            url,
            headers: { 'X-OmniVoice-Client-Id': slug },
          },
        },
      },
      null,
      2,
    ),
  };
}

/** Validate the configured backend without exporting URL credentials. */
export function backendEndpoint(baseUrl: string, endpoint: string) {
  try {
    const base = new URL(baseUrl);
    if (
      !['http:', 'https:'].includes(base.protocol) ||
      base.username ||
      base.password ||
      base.search ||
      base.hash
    )
      return null;
    return `${base.href.replace(/\/+$/, '')}${endpoint}`;
  } catch {
    return null;
  }
}
