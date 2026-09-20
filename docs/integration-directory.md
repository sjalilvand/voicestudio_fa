# Integration directory

Directory entries are illustrative, not paid sponsors, endorsements, or verified VoiceStudio integrations. Icons are bundled locally so viewing the catalog sends no logo requests to providers. Brand marks belong to their respective owners.

| Company | Official source | Icon source |
|---|---|---|
| Twilio | [Website](https://www.twilio.com) | Bundled site icon |
| Plivo | [Website](https://www.plivo.com) | Bundled site icon |
| Telnyx | [Website](https://telnyx.com) | Bundled site icon |
| n8n | [Website](https://n8n.io) | Bundled site icon |
| Zapier | [Website](https://zapier.com) | Bundled site icon |
| Make | [Website](https://www.make.com) | Bundled generic mark |
| GitHub | [Website](https://github.com) | Bundled site icon |
| GitHub Container Registry | [Website](https://ghcr.io) | Bundled GitHub icon |
| Docker | [Website](https://www.docker.com) | Bundled site icon |
| Model Context Protocol | [Website](https://modelcontextprotocol.io) | Bundled site icon |
| OpenAI Agents | [Guide](https://platform.openai.com/docs/guides/agents) | Bundled local mark |
| Claude Code | [Guide](https://docs.anthropic.com/en/docs/claude-code) | Bundled site icon |
| Codex CLI | [Repository](https://github.com/openai/codex) | Bundled local mark |
| VoiceStudio API | [Repository](https://github.com/debpalash/VoiceStudio) | Bundled local mark |

## Connect coding agents

The Claude Code and Cursor detail pages include a copyable MCP configuration for
VoiceStudio's current backend address and port. Merge the entry into `.mcp.json`
(Claude Code) or `.cursor/mcp.json` (Cursor), preserving your other servers. Keep
VoiceStudio running, then enable the server in your client. Use Settings → Sharing
→ MCP voice bindings to bind `claude-code` or `cursor` to a saved voice.

These configurations use Streamable HTTP and the client-ID header; they do not
install another backend or read/write agent configuration files. For a remote
backend, configure its required credentials in the client. Exported configurations
never contain stored credentials. Copying configuration does not prove the client
is connected; use its MCP tools/status view to confirm the connection.

The schemas follow the official [Claude Code MCP guide](https://code.claude.com/docs/en/mcp)
and [Cursor MCP guide](https://cursor.com/docs/mcp). Other directory entries remain
capability references, not implemented connectors. The catalog has one card per
route, retaining bundled logos and the correct category when entries overlap.
