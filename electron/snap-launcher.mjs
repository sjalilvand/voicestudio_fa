import { readFileSync, readdirSync } from 'node:fs';

const localesDir = new URL('./src/renderer/src/i18n/locales/', import.meta.url);
const quote = (value) => `'${value.replaceAll("'", "'\\''")}'`;
export const SNAP_PREFLIGHT_MARKER = '# VoiceStudio Snap sandbox preflight';

// This must run in command.sh: Chromium can abort before Electron loads main.
export function addSnapSandboxPreflight(command) {
  if (command.includes(SNAP_PREFLIGHT_MARKER)) return command;
  if (!command.startsWith('#!') || !command.includes('\n')) {
    throw new Error('Snap command.sh is missing its shell shebang');
  }
  const messages = Object.fromEntries(
    readdirSync(localesDir).filter((name) => name.endsWith('.json')).map((name) => {
      const locale = JSON.parse(readFileSync(new URL(name, localesDir), 'utf8'));
      const message = locale.snapLauncher?.permissionRequired;
      if (!message) throw new Error(`Missing Snap launcher translation: ${name}`);
      return [name.slice(0, -5), message];
    }),
  );
  const cases = Object.entries(messages).map(([locale, message]) => {
    const pattern = locale.replaceAll('-', '_');
    return `    ${pattern}|${pattern}[.@_]* ) message=${quote(message)} ;;`;
  }).join('\n');
  const newline = command.indexOf('\n') + 1;
  const preflight = `${SNAP_PREFLIGHT_MARKER}
if ! snapctl is-connected browser-support; then
  message=${quote(messages.en)}
  case "\${LC_ALL:-\${LC_MESSAGES:-\${LANG:-en}}}" in
${cases}
  esac
  message="$message

sudo snap connect voicestudio:browser-support"
  printf '%s\\n' "$message" >&2
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --no-markup --title=VoiceStudio --text="$message" || true
  fi
  exit 1
fi
`;
  return command.slice(0, newline) + preflight + command.slice(newline);
}
