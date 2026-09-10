import React, { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'react-hot-toast';
import { Download, RefreshCw } from 'lucide-react';
import { apiJson } from '../../api/client';
import { useEngines, useInstallModel, useRecommendations } from '../../api/hooks';
import { useAppStore } from '../../store';
import { Badge, Button } from '../../ui';

/**
 * SetupSummary — the Model Catalogue's first screen: what the app will use
 * right now for speech, transcription, dictation and the language model, one
 * line each, and a "Change" that jumps to that family's engine list below.
 *
 * Most users take the recommended engines and never come back; this is the
 * view built for them. Everything that used to compete for attention on the
 * old two-pane page (engine matrix, model store, stats) now sits under it,
 * reached only through Change.
 */
const DEVICE_LABEL = { cuda: 'CUDA', mps: 'MPS', rocm: 'ROCm', cpu: 'CPU', directml: 'DirectML' };

const STATUS_TONE = {
  ready: 'success',
  cpu: 'warn',
  setup: 'warn',
  off: 'neutral',
  missing: 'warn',
};

/** Pure: reduce one family's /engines payload to {name, device, status}. */
export function summarizeFamily(family, familyData) {
  const active = familyData?.active;
  const backends = familyData?.backends || [];
  if (family === 'llm' && (!active || active === 'off')) {
    return { name: null, device: null, status: 'off' };
  }
  const entry = backends.find((b) => b.id === active);
  const name = entry?.display_name || active || null;
  if (!entry || entry.available === false) return { name, device: null, status: 'setup' };
  const routing = entry.routing_status;
  const device =
    routing === 'n/a' ? 'remote' : DEVICE_LABEL[entry.effective_device] || entry.effective_device;
  return {
    name,
    device: device || null,
    status: routing === 'cpu_fallback' ? 'cpu' : 'ready',
  };
}

/** Pure: the dictation line from /dictation/models + the model_id pref. */
export function summarizeDictation(data, modelId) {
  const models = Array.isArray(data?.models) ? data.models : [];
  const selected =
    models.find((m) => m.id === modelId) || models.find((m) => m.recommended) || models[0];
  if (!selected) return { name: null, device: null, status: 'setup' };
  if (data?.engine_available === false)
    return { name: selected.label, device: null, status: 'setup' };
  return {
    name: selected.label,
    device: DEVICE_LABEL.cpu,
    status: selected.installed ? 'ready' : 'missing',
  };
}

export default function SetupSummary({ onChange }) {
  const { t } = useTranslation();
  const enginesQuery = useEngines();
  const recoQuery = useRecommendations();
  const installMutation = useInstallModel();
  const [installing, setInstalling] = useState(false);

  const modelId = useAppStore((s) => s.dictationModelId);
  const loadPrefs = useAppStore((s) => s.loadDictationPrefs);
  const dictationLoaded = useAppStore((s) => s.dictationLoaded);
  useEffect(() => {
    if (!dictationLoaded) loadPrefs?.();
  }, [dictationLoaded, loadPrefs]);
  // Same query key as the quick-menu picker so both read one cache entry.
  const dictationQuery = useQuery({
    queryKey: ['dictation-models'],
    queryFn: () => apiJson('/dictation/models'),
    staleTime: 10_000,
    retry: false,
  });

  const engines = enginesQuery.data;
  const rows = useMemo(
    () => [
      {
        key: 'speech',
        family: 'tts',
        label: t('header.speech'),
        ...summarizeFamily('tts', engines?.tts),
      },
      {
        key: 'transcription',
        family: 'asr',
        label: t('projects.transcription'),
        ...summarizeFamily('asr', engines?.asr),
      },
      {
        key: 'dictation',
        family: 'asr',
        label: t('settings.dictation'),
        ...summarizeDictation(dictationQuery.data, modelId),
      },
      {
        key: 'llm',
        family: 'llm',
        label: t('models.role_llm'),
        ...summarizeFamily('llm', engines?.llm),
      },
    ],
    [t, engines, dictationQuery.data, modelId],
  );

  const statusLabel = {
    ready: t('models.ready_badge'),
    cpu: t('catalogue.status_cpu'),
    setup: t('catalogue.status_setup'),
    off: t('catalogue.status_off'),
    missing: t('models.not_installed'),
  };

  const reco = recoQuery.data;
  const missing = reco?.models?.filter((m) => !m.installed) || [];
  const installRest = async () => {
    if (missing.length === 0) return;
    setInstalling(true);
    try {
      await Promise.all(missing.map((m) => installMutation.mutateAsync(m.repo_id)));
      toast.success(t('models.started_downloading', { count: missing.length }));
    } catch (e) {
      toast.error(t('models.install_failed', { message: e?.message || e }));
    } finally {
      setInstalling(false);
    }
  };

  return (
    <section
      aria-labelledby="setup-summary-title"
      data-testid="setup-summary"
      className="mb-[32px] rounded-[14px] border border-border bg-card/40 px-[20px] py-[6px] font-sans"
    >
      <h2 id="setup-summary-title" className="sr-only">
        {t('catalogue.summary_title')}
      </h2>
      <dl className="m-0 divide-y divide-border">
        {rows.map((row) => (
          <div
            key={row.key}
            data-testid={`setup-row-${row.key}`}
            className="flex flex-wrap items-center gap-x-[16px] gap-y-[4px] py-[10px]"
          >
            <dt className="w-[128px] shrink-0 text-sm font-semibold text-foreground">
              {row.label}
            </dt>
            <dd className="m-0 flex min-w-0 flex-1 flex-wrap items-center gap-x-[8px] text-sm text-muted-foreground">
              {enginesQuery.isLoading && !engines && row.key !== 'dictation' ? (
                <span>{t('common.loading')}</span>
              ) : (
                <>
                  {row.name && (
                    <span
                      className="truncate text-foreground"
                      data-testid={`setup-name-${row.key}`}
                    >
                      {row.name}
                    </span>
                  )}
                  {row.device && (
                    <>
                      {row.name && <span aria-hidden="true">·</span>}
                      <span className="font-mono text-[11px] uppercase tracking-[0.03em]">
                        {row.device === 'remote' ? t('catalogue.device_remote') : row.device}
                      </span>
                    </>
                  )}
                  {(row.name || row.device) && <span aria-hidden="true">·</span>}
                  <Badge
                    tone={STATUS_TONE[row.status]}
                    size="xs"
                    data-testid={`setup-status-${row.key}`}
                  >
                    {statusLabel[row.status]}
                  </Badge>
                </>
              )}
            </dd>
            <Button
              variant="subtle"
              size="sm"
              onClick={() => onChange?.(row.family)}
              data-testid={`setup-change-${row.key}`}
            >
              {t('catalogue.change')}
            </Button>
          </div>
        ))}
      </dl>
      {reco && (
        <div
          data-testid="setup-reco"
          className="flex flex-wrap items-center gap-x-[12px] gap-y-[6px] border-t border-border py-[10px] text-xs text-muted-foreground"
        >
          <span className="min-w-0 flex-1">
            {reco.all_installed || missing.length === 0
              ? t('models.reco_installed_for', { device: reco.device?.label })
              : t('catalogue.reco_line', {
                  installed: reco.models.length - missing.length,
                  total: reco.models.length,
                  device: reco.device?.label,
                  remaining: reco.download_gb_remaining,
                })}
          </span>
          {missing.length > 0 && (
            <Button
              variant="primary"
              size="sm"
              onClick={installRest}
              disabled={installing}
              leading={
                installing ? <RefreshCw size={11} className="spinner" /> : <Download size={11} />
              }
              data-testid="setup-install-rest"
            >
              {installing ? t('models.starting') : t('catalogue.install_rest')}
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
