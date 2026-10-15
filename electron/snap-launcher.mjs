// Canonical's Electron Snap guidance uses strict Snap confinement instead of
// Chromium's inner sandbox. Apply this only to the packaged Snap command.sh.
// https://snapcraft.io/docs/reference/interfaces/browser-support-interface/
const executable = '"$SNAP/voicestudio"';
const argumentsSuffix = ' "$@"';
const configuredInvocation = `${executable} --no-sandbox${argumentsSuffix}`;

export function verifySnapLauncher(command) {
  if (!command.startsWith('#!') ||
      !command.includes(configuredInvocation) ||
      command.includes('snapctl is-connected browser-support')) {
    throw new Error('Snap launcher must use strict confinement without a Chromium sandbox permission gate');
  }
}

export function configureSnapLauncher(command) {
  if (!command.startsWith('#!') || !command.includes('\n')) {
    throw new Error('Snap launcher is missing its shell shebang');
  }
  const originalInvocation = `${executable}${argumentsSuffix}`;
  const configured = command.includes(configuredInvocation)
    ? command
    : command.replace(originalInvocation, configuredInvocation);
  verifySnapLauncher(configured);
  return configured;
}
