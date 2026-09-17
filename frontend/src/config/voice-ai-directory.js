// Integration directory links, not sponsors, rankings, or connected accounts.
// Official icon sources and verification links: docs/integration-directory.md.
import genericLogo from '../assets/integrations/integration-generic.svg';
import twilioLogo from '../assets/integrations/twilio.png';
import plivoLogo from '../assets/integrations/plivo.svg';
import telnyxLogo from '../assets/integrations/telnyx.ico';
import n8nLogo from '../assets/integrations/n8n.ico';
import zapierLogo from '../assets/integrations/zapier.ico';
import githubLogo from '../assets/integrations/github.png';
import dockerLogo from '../assets/integrations/docker.png';
import mcpLogo from '../assets/integrations/mcp.png';
import anthropicLogo from '../assets/integrations/anthropic.png';

export const VOICE_AI_DIRECTORY = [
  {
    name: 'Twilio',
    url: 'https://www.twilio.com',
    logoUrl: twilioLogo,
    detailKeys: ['nav.dub', 'settings.mcp_title'],
  },
  {
    name: 'Plivo',
    url: 'https://www.plivo.com',
    logoUrl: plivoLogo,
    detailKeys: ['nav.dub', 'engineSidebar.asr'],
  },
  {
    name: 'Telnyx',
    url: 'https://telnyx.com',
    logoUrl: telnyxLogo,
    detailKeys: ['nav.dub', 'engineSidebar.tts'],
  },
  {
    name: 'n8n',
    url: 'https://n8n.io',
    logoUrl: n8nLogo,
    detailKeys: ['tools.title', 'settings.mcp_title'],
  },
  { name: 'Zapier', url: 'https://zapier.com', logoUrl: zapierLogo, detailKeys: ['tools.title'] },
  { name: 'Make', url: 'https://www.make.com', logoUrl: genericLogo, detailKeys: ['tools.title'] },
  {
    name: 'GitHub',
    url: 'https://github.com',
    logoUrl: githubLogo,
    detailKeys: ['tools.title', 'settings.mcp_title'],
  },
  {
    name: 'GitHub Container Registry',
    url: 'https://ghcr.io',
    logoUrl: githubLogo,
    detailKeys: ['tools.title', 'settings.mcp_title'],
  },
  {
    name: 'Docker',
    url: 'https://www.docker.com',
    logoUrl: dockerLogo,
    detailKeys: ['tools.title'],
  },
  {
    name: 'Model Context Protocol',
    url: 'https://modelcontextprotocol.io',
    logoUrl: mcpLogo,
    detailKeys: ['settings.mcp_title', 'tools.title'],
  },
  {
    name: 'OpenAI Agents',
    url: 'https://platform.openai.com/docs/guides/agents',
    logoUrl: genericLogo,
    detailKeys: ['dub.choose_translation_agent', 'settings.mcp_title'],
  },
  {
    name: 'Claude Code',
    url: 'https://docs.anthropic.com/en/docs/claude-code',
    logoUrl: anthropicLogo,
    detailKeys: ['dub.choose_translation_agent', 'tools.title'],
  },
  {
    name: 'Codex CLI',
    url: 'https://github.com/openai/codex',
    logoUrl: genericLogo,
    detailKeys: ['dub.choose_translation_agent', 'tools.title'],
  },
  {
    name: 'VoiceStudio API',
    url: 'https://github.com/debpalash/VoiceStudio',
    logoUrl: genericLogo,
    detailKeys: ['tools.title', 'engineSidebar.tts', 'engineSidebar.asr'],
  },
];
