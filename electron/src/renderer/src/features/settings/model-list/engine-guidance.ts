import type { TFunction } from 'i18next';
import type { EngineBackend } from '@/lib/api/types';

const packageCommands = new Map([
  ['whisperx', 'pip install whisperx'],
  ['faster-whisper', 'pip install faster-whisper'],
  ['moonshine', 'uv pip install moonshine-onnx'],
  ['funasr', 'pip install funasr'],
  ['sherpa-onnx-asr', 'uv add sherpa-onnx'],
]);
const appleCommands = new Map([
  ['mlx-whisper', 'pip install mlx-whisper'],
  ['parakeet-mlx', 'uv add parakeet-mlx'],
]);

/** Localize known authored ASR guidance; older/custom engines keep their hint. */
export function asrSetupHint(engine: EngineBackend, t: TFunction) {
  if (!engine.install_hint) return engine.install_hint;
  const command = packageCommands.get(engine.id);
  if (command) return t('engines.asrSetupPackageInstall', { command });
  const appleCommand = appleCommands.get(engine.id);
  if (appleCommand) return t('engines.asrSetupApplePackageInstall', { command: appleCommand });
  switch (engine.id) {
    case 'pytorch-whisper':
      return t('engines.asrSetupBundled');
    case 'whisper-cpp':
      return t('engines.asrSetupWhisperCpp', {
        binary: 'whisper-cli',
        folder: 'backend/engines/whisper_cpp/bin/',
      });
    case 'nemo-parakeet':
      return t('engines.asrSetupNemoParakeet', {
        nemoRequirement: 'transformers>=4.57,<4.58',
        appRequirement: 'transformers>=5.3',
      });
    case 'faster-whisper-isolated':
      return t('engines.asrSetupIsolated');
    case 'openai-compat-asr':
      return t('engines.asrSetupRemote');
    default:
      return engine.install_hint;
  }
}

/** Match only the API's owned sentences, never arbitrary probe diagnostics. */
export function engineUnavailableReason(reason: string | null | undefined, t: TFunction) {
  for (const destination of ['Model Catalogue', 'Settings → Models']) {
    if (reason === `This engine's package isn't installed yet. Install it from ${destination}.`)
      return t('engines.setupStatusNotInstalled');
    if (
      reason ===
      `License not accepted yet. Review and accept it in ${destination} to enable this engine.`
    )
      return t('engines.setupStatusLicense');
    if (
      reason ===
      `This engine needs to be configured before it can run. Open ${destination} to finish setting it up.`
    )
      return t('engines.setupStatusNeedsConfig');
    if (
      reason ===
      `A file this engine needs is missing or unreadable. Reinstall it from ${destination}.`
    )
      return t('engines.setupStatusFileMissing');
  }
  return reason;
}
