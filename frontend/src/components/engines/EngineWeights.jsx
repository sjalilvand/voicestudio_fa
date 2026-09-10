import React from 'react';
import { Check, Download, RefreshCw, Trash2, Wrench, X } from 'lucide-react';
import { Badge, Button, Progress } from '../../ui';
import { cn } from '@/lib/utils';
import { fmtBytes } from '../settings/models/format';
import { describeProgress } from '../settings/models/progressText';
import DictationModelPicker from '../DictationModelPicker';

/** The catalogue weights an engine loads (models.yaml `engines:` mapping). */
export function weightsForEngine(models, engineId) {
  return (models || []).filter((m) => Array.isArray(m.engines) && m.engines.includes(engineId));
}

/**
 * EngineWeights — the downloadable weights of ONE engine, inside its detail
 * panel: one line per model (label, size, state, one action) with the
 * download progress or install error folded under the line while it lasts.
 *
 * This is the same install / cancel / remove / reinstall flow the model
 * store drives (useModelDownloads), so a download started here shows the
 * same progress everywhere. The sherpa-onnx dictation engine keeps its own
 * picker: choosing a dictation model is a preference, not just a download.
 */
export default function EngineWeights({ engineId, models, downloads, t }) {
  if (!downloads) return null;
  if (engineId === 'sherpa-onnx-asr') {
    return (
      // The picker carries its own "Dictation model" label — no second heading.
      <section className="flex flex-col" data-testid={`engine-weights-${engineId}`}>
        <DictationModelPicker />
      </section>
    );
  }
  const rows = weightsForEngine(models, engineId);
  return (
    <section className="flex flex-col gap-[4px]" data-testid={`engine-weights-${engineId}`}>
      <h4 className="m-0 font-mono text-[11px] font-medium uppercase tracking-[var(--chrome-label-track)] text-muted-foreground">
        {t('engines.weights')}
      </h4>
      {rows.length === 0 ? (
        <p
          className="m-0 text-[11px] leading-[1.5] text-muted-foreground"
          data-testid="engine-weights-none"
        >
          {t('engines.noWeights')}
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col p-0">
          {rows.map((m) => (
            <WeightRow key={m.repo_id} m={m} downloads={downloads} t={t} />
          ))}
        </ul>
      )}
    </section>
  );
}

function WeightRow({ m, downloads, t }) {
  const rt = downloads.getRowRuntime(m);
  const resident = downloads.getResidency?.(m);
  const size = m.installed ? fmtBytes(m.size_on_disk_bytes) : `${m.size_gb} GB`;
  const quiet = !m.installed && !rt.showBar;
  return (
    <li
      className="flex flex-col gap-[4px] border-t border-border/70 py-[7px] first:border-0"
      data-testid={`weight-${m.repo_id}`}
      data-installed={m.installed ? 'true' : 'false'}
    >
      <div className="flex min-w-0 items-center gap-[8px]">
        {m.installed ? (
          <Check size={12} className="shrink-0 text-success" aria-label={t('models.installed')} />
        ) : (
          <span className="inline-block h-[12px] w-[12px] shrink-0" aria-hidden="true" />
        )}
        <span
          className={cn(
            'min-w-0 flex-1 truncate text-[13px]',
            quiet ? 'text-muted-foreground' : 'text-foreground',
          )}
          title={m.note ? `${m.repo_id} · ${m.note}` : m.repo_id}
        >
          {m.label}
        </span>
        {m.required && (
          <Badge tone="brand" size="xs" className="shrink-0">
            {t('models.required_tag')}
          </Badge>
        )}
        {!m.required && m.curated && (
          <Badge
            tone="success"
            size="xs"
            className="shrink-0"
            title={t('models.recommended_title')}
          >
            {t('voicePanel.badge_recommended')}
          </Badge>
        )}
        {resident && (
          <Badge tone="info" size="xs" className="shrink-0" title={t('models.in_memory_title')}>
            {t('models.in_memory')}
          </Badge>
        )}
        <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
          {size}
        </span>
        <span className="inline-flex shrink-0 items-center gap-[2px]">
          {rt.isInstalling || (rt.showBar && !rt.isDeleting) ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => downloads.onCancel(m.repo_id)}
              leading={<X size={11} />}
              aria-label={`${t('models.cancel_btn')} ${m.label}`}
            >
              {rt.aggPct != null ? `${Math.round(rt.aggPct)}%` : t('models.cancel_btn')}
            </Button>
          ) : rt.isDeleting || rt.rowBusy ? (
            <span className="font-mono text-[11px] text-muted-foreground">
              {t('models.working')}
            </span>
          ) : m.installed ? (
            <>
              {resident?.unloadable && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => downloads.onUnload(m.repo_id)}
                  aria-label={t('models.unload_aria', { repoId: m.repo_id })}
                >
                  {t('models.unload_btn')}
                </Button>
              )}
              <Button
                variant="icon"
                iconSize="sm"
                onClick={() => downloads.onReinstall(m.repo_id)}
                title={t('models.reinstall_btn')}
                aria-label={`${t('models.reinstall_btn')} ${m.label}`}
              >
                <RefreshCw size={11} />
              </Button>
              <Button
                variant="icon"
                iconSize="sm"
                onClick={() => downloads.onDelete(m.repo_id)}
                title={t('models.delete_btn')}
                aria-label={`${t('models.delete_btn')} ${m.label}`}
              >
                <Trash2 size={11} />
              </Button>
            </>
          ) : rt.unsupported ? (
            <span className="font-mono text-[11px] text-muted-foreground">
              {(m.platforms || []).join(', ')}
            </span>
          ) : (
            <Button
              size="sm"
              variant="subtle"
              onClick={() => downloads.onInstall(m.repo_id)}
              leading={m.incomplete ? <Wrench size={11} /> : <Download size={11} />}
              title={m.incomplete ? t('models.repair_title') : undefined}
              aria-label={`${m.incomplete ? t('models.repair_btn') : t('models.install_btn')} ${m.label}`}
              data-testid={`weight-install-${m.repo_id}`}
            >
              {m.incomplete ? t('models.repair_btn') : t('models.install_btn')}
            </Button>
          )}
        </span>
      </div>
      {rt.showBar && (
        <div
          className="flex flex-col gap-[3px] pl-[20px]"
          data-testid={`weight-progress-${m.repo_id}`}
        >
          <Progress value={rt.aggPct} tone={rt.isDeleting ? 'warn' : 'brand'} size="xs" />
          <span className="font-mono text-[11px] leading-[1.4] tabular-nums text-muted-foreground">
            {describeProgress(rt, t, downloads.speedRef, m.repo_id)}
          </span>
        </div>
      )}
      {rt.phase === 'install_error' && rt.rs?.error && (
        <div
          className="flex flex-wrap items-start gap-[6px] pl-[20px] text-[11px] text-destructive"
          role="alert"
        >
          <span className="min-w-0 flex-1">
            {t('models.install_error', { error: rt.rs.error })}
          </span>
          <span className="inline-flex shrink-0 items-center gap-[4px]">
            <Button
              size="sm"
              variant="subtle"
              onClick={() => downloads.onInstall(m.repo_id)}
              leading={<RefreshCw size={10} />}
            >
              {t('models.retry_btn')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => downloads.onDismissError(m.repo_id)}>
              {t('common.dismiss')}
            </Button>
          </span>
        </div>
      )}
    </li>
  );
}
