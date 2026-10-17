/** The only GitHub request the app makes by policy (star badge); tests answer it with a stub. */
export const STAR_COUNT_URL = 'https://api.github.com/repos/debpalash/VoiceStudio';
export const STAR_COUNT_STUB = { stargazers_count: 1234 };

const LOCAL_SCHEMES = new Set(['app:', 'file:', 'data:', 'blob:', 'devtools:']);
const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]']);

/** True when a request stays on this machine (local schemes or an exact loopback host). */
export function isAllowedRequest(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (LOCAL_SCHEMES.has(parsed.protocol)) return true;
  return (
    (parsed.protocol === 'http:' || parsed.protocol === 'https:') &&
    LOOPBACK_HOSTS.has(parsed.hostname)
  );
}
