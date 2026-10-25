import { TERMINAL_MODEL_INSTALL_STATES } from '@/hooks/use-model-install-sync';
import type { CatalogueModel } from '../model-catalogue-query';
import type { ModelOps } from './model-ops';

const GATED_TOPICS = new Set([
  'HF_AUTH_FAILED',
  'PYANNOTE_LICENSE_REQUIRED',
  'POCKETTTS_GATED_WEIGHTS',
]);

/** Where a failed download's docs topic is fixed. */
function recoveryFor(topic: string | undefined) {
  switch (topic) {
    case 'DISK_SPACE_LOW':
    case 'AUDIO_IO_FAILED':
    case 'OS_INVALID_ARGUMENT':
      return { to: '/settings/storage' as const, label: 'settings.storage' };
    case 'HF_MIRROR_UNREACHABLE':
    case 'HF_MIRROR_GATED':
      return { to: '/settings/models' as const, label: 'models.mirror_title' };
    case 'HF_AUTH_FAILED':
    case 'PYANNOTE_LICENSE_REQUIRED':
    case 'POCKETTTS_GATED_WEIGHTS':
      return { to: '/settings/credentials' as const, label: 'settings.credentials' };
    case 'SOCKS_PROXY_SUPPORT_MISSING':
    case 'SSL_HANDSHAKE_FAILURE':
    case 'TLS_CONNECTION_DROPPED':
      return { to: '/settings/network' as const, label: 'settings.network' };
    case 'GPU_OOM':
    case 'COMPUTE_TYPE_UNSUPPORTED':
    case 'WINDOWS_PAGING_FILE_TOO_SMALL':
      return { to: '/settings/performance' as const, label: 'settings.perf_title' };
    default:
      return null;
  }
}

function formatEta(seconds: number | null | undefined) {
  if (!seconds || seconds <= 0) return '';
  if (seconds < 60) return `~${Math.ceil(seconds)}s`;
  if (seconds < 3600) return `~${Math.ceil(seconds / 60)}m`;
  return `~${(seconds / 3600).toFixed(1)}h`;
}

/** Everything a model row needs to know about its download job. */
export function describeJob(model: CatalogueModel, ops: ModelOps) {
  const job = ops.jobs.find((entry) => entry.repo_id === model.repo_id);
  const failed = job?.state === 'failed' && !ops.isDismissed(model.repo_id);
  return {
    job,
    downloading: Boolean(job && !TERMINAL_MODEL_INSTALL_STATES.has(job.state)),
    cancelling: job?.state === 'cancelling' || job?.phase === 'cancelling',
    failed,
    gatedFailure: failed && GATED_TOPICS.has(job?.docs_topic ?? ''),
    retryAfter: Math.max(0, Math.ceil(job?.retry_after_seconds ?? 0)),
    recovery: recoveryFor(job?.docs_topic),
    pct: job?.total_bytes
      ? Math.min(100, Math.round(((job.bytes_done ?? 0) / job.total_bytes) * 100))
      : null,
    eta: formatEta(job?.eta_seconds),
  };
}

export type JobInfo = ReturnType<typeof describeJob>;
