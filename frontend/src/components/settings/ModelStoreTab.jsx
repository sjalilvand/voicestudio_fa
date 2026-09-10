import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { RefreshCw, Search, Zap } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { useTranslation } from 'react-i18next';
import { setupDownloadStreamUrl } from '../../api/setup';
import { listLoadedModels, unloadLoadedModel } from '../../api/system';
import { useModels, useRecommendations, useInstallModel, useDeleteModel } from '../../api/hooks';
import { Button } from '../../ui';
import { Input } from '@/components/ui/input';
import { askConfirm } from './native';
import { computeRowRuntime } from './models/runtime';
import {
  downloadKey,
  progressForRepo,
  reduceModelDownloadEvent,
  isAutoPurgeTerminal,
} from './models/downloadReducer';
import { makeModelColumns } from './models/columns';
import { FAMILY_SECTIONS, groupModels, modelSectionKey, scopeReco } from './models/sections';
import RecoBanner from './models/RecoBanner';
import ModelSection from './models/ModelSection';

/**
 * Model store — the downloadable weights for one engine family (or all of
 * them when `family` is null), grouped by capability (TTS / ASR offline /
 * Dictation streaming / Diarisation), with install state and install /
 * reinstall / delete per row. The curated "for your system" preset leads
 * (RecoBanner, scoped to the family); platform-incompatible rows collapse
 * behind a per-section toggle. Per-model download progress is pulled from
 * the shared /setup/download-stream SSE.
 *
 * Storage stats, the HF token and the voice-preview toggle used to sit on
 * this list; they live in Settings → Storage / Credentials now.
 */
export default function ModelStoreTab({ info, family = null }) {
  const { t } = useTranslation();
  // Role labels — localized (diarization is an on-disk spelling alias for
  // diarisation; both map to the same label).
  const MODEL_ROLE_LABEL = useMemo(
    () => ({
      all: t('models.role_all'),
      tts: t('models.role_tts'),
      asr: t('models.role_asr'),
      diarisation: t('models.role_diarisation'),
      diarization: t('models.role_diarisation'),
      llm: t('models.role_llm'),
      other: t('models.role_other'),
    }),
    [t],
  );
  const modelsQuery = useModels();
  const recoQuery = useRecommendations();
  const data = modelsQuery.data;
  const loading = modelsQuery.isLoading;
  const reco = recoQuery.data;
  const familyReco = useMemo(() => scopeReco(reco, family), [reco, family]);
  const installMutation = useInstallModel();
  const deleteMutation = useDeleteModel();

  const [busy, setBusy] = useState(new Set()); // repo_ids currently working
  // Per-repo active state. Tracks aggregate download across all files of
  // a running install so the row can show a determinate progress bar.
  // { [repo_id]: { phase, files: { [filename]: { downloaded, total, pct } }, error } }
  const [rowState, setRowState] = useState({});
  const [query, setQuery] = useState('');
  const [installingReco, setInstallingReco] = useState(false);
  const esRef = React.useRef(null);
  // Track download speed per repo: { [repo_id]: { lastBytes, lastTime, speed } }
  const speedRef = React.useRef({});
  // Tick counter — forces re-render every second while a download is active
  // so speed/ETA displays update smoothly between SSE events.
  const [, setTick] = useState(0);
  // Boolean derived from rowState so the interval effect below only re-runs
  // when activity starts/stops — not on every SSE progress event (several per
  // second during installs), which would clear + recreate the 1s tick forever.
  const hasActive = useMemo(
    () =>
      Object.values(rowState).some((s) =>
        ['install_start', 'active', 'delete_start'].includes(s.phase),
      ),
    [rowState],
  );
  useEffect(() => {
    if (!hasActive) return;
    const iv = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(iv);
  }, [hasActive]);

  // Open the progress stream once when the tab mounts; close on unmount.
  useEffect(() => {
    const es = new EventSource(setupDownloadStreamUrl());
    esRef.current = es;
    es.onmessage = (evt) => {
      try {
        const ev = JSON.parse(evt.data);
        if (!ev?.repo_id) return;
        // Pure reducer (see downloadReducer.js) — keeps every SSE transition,
        // including the "install_error persists" fix, unit-testable.
        setRowState((prev) => reduceModelDownloadEvent(prev, ev));
      } catch {
        /* keepalive / ignore */
      }
    };
    return () => es.close();
  }, []);

  // When a SUCCESS terminator fires (install_done / delete_done /
  // install_cancelled), refresh the list so "installed" flips server-side info
  // into the row, then purge the transient entry so the row reverts to the
  // authoritative `installed` flag. `install_error` is deliberately excluded
  // (isAutoPurgeTerminal) — an error row must persist with a Retry/Dismiss
  // affordance until the user acts on it (P1-A), instead of vanishing ~800ms
  // later and hiding the mirror-aware failure text.
  useEffect(() => {
    const term = Object.entries(rowState).find(([, s]) => isAutoPurgeTerminal(s.phase));
    if (!term) return;
    const t = setTimeout(() => {
      modelsQuery.refetch();
      recoQuery.refetch();
      // Clear stale speed data for this repo.
      delete speedRef.current[term[0]];
      setRowState((prev) => {
        const next = { ...prev };
        delete next[term[0]];
        return next;
      });
    }, 800);
    return () => clearTimeout(t);
  }, [rowState, modelsQuery, recoQuery]);

  // Memory residency: repo_id (checkpoint) → its /model/loaded entry. Marks
  // rows whose weights are resident in RAM/VRAM right now and enables the
  // Unload affordance where the backend says the entry is unloadable.
  // Advisory — a fetch failure just means no chips, never a broken tab.
  const [loadedModels, setLoadedModels] = useState([]);
  const refreshLoaded = useCallback(async () => {
    try {
      const res = await listLoadedModels();
      setLoadedModels(res?.models || []);
    } catch {
      setLoadedModels([]);
    }
  }, []);
  useEffect(() => {
    refreshLoaded();
  }, [refreshLoaded]);
  const residencyByRepo = useMemo(() => {
    const map = {};
    for (const lm of loadedModels) {
      if (lm?.checkpoint) map[lm.checkpoint] = lm;
    }
    return map;
  }, [loadedModels]);
  const getResidency = useCallback((m) => residencyByRepo[m.repo_id] || null, [residencyByRepo]);
  const onUnload = useCallback(
    async (repoId) => {
      const entry = residencyByRepo[repoId];
      if (!entry) return;
      try {
        await unloadLoadedModel(entry.id);
        toast.success(t('models.unloaded_toast'));
      } catch (e) {
        toast.error(t('models.unload_failed', { message: e.message || String(e) }));
      } finally {
        refreshLoaded();
      }
    },
    [residencyByRepo, refreshLoaded, t],
  );

  const reload = useCallback(() => {
    modelsQuery.refetch();
    recoQuery.refetch();
    refreshLoaded();
  }, [modelsQuery, recoQuery, refreshLoaded]);

  const withBusy = useCallback(async (repoId, fn, successMsg) => {
    setBusy((prev) => new Set(prev).add(repoId));
    try {
      await fn();
      if (successMsg) toast.success(successMsg);
    } catch (e) {
      toast.error(e.message || String(e));
    } finally {
      setBusy((prev) => {
        const s = new Set(prev);
        s.delete(repoId);
        return s;
      });
    }
  }, []);

  const onInstall = useCallback(
    (repoId) =>
      withBusy(repoId, () => installMutation.mutateAsync(repoId), t('models.install_started')),
    [installMutation, withBusy],
  );
  const onDelete = useCallback(
    async (repoId) => {
      if (
        !(await askConfirm(
          t('models.delete_confirm', { repoId }),
          t('models.delete_confirm_title'),
        ))
      )
        return;
      return withBusy(
        repoId,
        () => deleteMutation.mutateAsync(repoId),
        t('models.deleted', { repoId }),
      );
    },
    [deleteMutation, withBusy],
  );
  const onReinstall = useCallback(
    async (repoId) => {
      if (
        !(await askConfirm(
          t('models.reinstall_confirm', { repoId }),
          t('models.reinstall_confirm_title'),
        ))
      )
        return;
      await withBusy(
        repoId,
        async () => {
          await deleteMutation.mutateAsync(repoId);
          await installMutation.mutateAsync(repoId);
        },
        t('models.reinstalling'),
      );
    },
    [deleteMutation, installMutation, withBusy],
  );
  // Cancel an in-flight install (P2-A / FDL-11). Optimistically flip the row to
  // `install_cancelled` (an auto-purge terminal) for instant feedback; the
  // backend also emits `install_cancelled` when the retry loop unwinds.
  const onCancel = useCallback(async (repoId) => {
    try {
      const { cancelInstallModel } = await import('../../api/setup');
      await cancelInstallModel(repoId);
      setRowState((prev) => ({
        ...prev,
        [downloadKey('local', repoId)]: {
          ...(prev[downloadKey('local', repoId)] || { files: {} }),
          phase: 'install_cancelled',
        },
      }));
    } catch (e) {
      toast.error(e.message || String(e));
    }
  }, []);
  // Dismiss a persisted install_error row (P1-A): drop the transient entry so
  // the row reverts to its authoritative /models state, and refresh in case a
  // partial download changed on-disk state.
  const onDismissError = useCallback(
    (repoId) => {
      setRowState((prev) => {
        const next = { ...prev };
        for (const key of Object.keys(next)) {
          if (key.endsWith(`\u0000${repoId}`)) delete next[key];
        }
        return next;
      });
      delete speedRef.current[repoId];
      modelsQuery.refetch();
      recoQuery.refetch();
    },
    [modelsQuery, recoQuery],
  );

  const onInstallRecommended = async () => {
    if (!familyReco) return;
    const missing = familyReco.models.filter((m) => !m.installed);
    if (missing.length === 0) {
      toast.success(t('models.recommended_installed'));
      return;
    }
    setInstallingReco(true);
    try {
      // Parallel install — backend /models/install spawns each download on
      // its own asyncio task so ordering doesn't matter.
      await Promise.all(missing.map((m) => installMutation.mutateAsync(m.repo_id)));
      toast.success(t('models.started_downloading', { count: missing.length }));
    } catch (e) {
      toast.error(t('models.install_failed', { message: e.message || e }));
    } finally {
      setInstallingReco(false);
    }
  };

  // The family's slice of the catalog (all of it when unscoped).
  const allModels = React.useMemo(() => {
    const models = data?.models || [];
    const keep = family ? FAMILY_SECTIONS[family] || [] : null;
    return keep ? models.filter((m) => keep.includes(modelSectionKey(m))) : models;
  }, [data, family]);
  // Grouped catalog: TTS / ASR (offline transcription) / Dictation (streaming)
  // / Diarisation, with the search query applied per-section (pure helper —
  // matches the same fields the old global filter did).
  const sections = React.useMemo(() => groupModels(allModels, query), [allModels, query]);
  const MODEL_SECTION_LABEL = useMemo(
    () => ({
      tts: t('models.section_tts'),
      asr: t('models.section_asr'),
      dictation: t('models.section_dictation'),
      diarisation: t('models.section_diarisation'),
      other: t('models.section_other'),
    }),
    [t],
  );

  const getRowRuntime = React.useCallback(
    (m) => computeRowRuntime(m, { [m.repo_id]: progressForRepo(rowState, m.repo_id) }, busy),
    [busy, rowState],
  );

  const columns = React.useMemo(
    () =>
      makeModelColumns({
        t,
        getRowRuntime,
        speedRef,
        MODEL_ROLE_LABEL,
        onInstall,
        onDelete,
        onReinstall,
        onCancel,
        onDismissError,
        getResidency,
        onUnload,
      }),
    [
      getRowRuntime,
      onDelete,
      onInstall,
      onReinstall,
      onCancel,
      onDismissError,
      getResidency,
      onUnload,
      MODEL_ROLE_LABEL,
      t,
    ],
  );

  if (loading && !data) {
    return (
      <div className="px-[2px] py-[24px] font-sans text-sm text-muted-foreground">
        {t('common.loading')}
      </div>
    );
  }
  if (!data) return null;

  return (
    <section className="flex min-h-0 flex-col font-sans" data-testid="model-list-panel">
      <div className="mb-[18px] flex flex-wrap items-center gap-[10px] px-[2px]">
        <div className="relative w-full min-w-[160px] max-w-[420px]">
          <Search
            size={13}
            className="pointer-events-none absolute left-[10px] top-1/2 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            type="search"
            className="h-8 pl-[30px] text-sm"
            placeholder={t('models.search_placeholder')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label={t('models.search_label')}
          />
        </div>
        {info?.fast_download?.xet_enabled && (
          <span
            className="inline-flex items-center gap-1 font-mono text-[11px] text-accent"
            title={
              t('models.fast_download_title', {
                version: info.fast_download.xet_version || 'Xet',
              }) ||
              `Fast downloads via Xet ${info.fast_download.xet_version || ''} — parallel chunked transfer`
            }
          >
            <Zap size={11} aria-hidden="true" />{' '}
            {t('models.fast_download_badge') || 'fast download'}
          </span>
        )}
        <span className="flex-1" />
        <Button
          variant="subtle"
          size="sm"
          onClick={reload}
          loading={loading}
          leading={<RefreshCw size={11} />}
        >
          {t('common.refresh')}
        </Button>
      </div>

      <RecoBanner
        reco={familyReco}
        t={t}
        installMutation={installMutation}
        installingReco={installingReco}
        setInstallingReco={setInstallingReco}
        onInstallRecommended={onInstallRecommended}
        onInstall={onInstall}
        getRowRuntime={getRowRuntime}
        diskFreeGb={data.disk_free_gb}
      />

      <div className="min-h-0 flex-1" data-testid="model-list-area">
        {sections.map((group) => (
          <ModelSection
            key={group.key}
            sectionKey={group.key}
            title={MODEL_SECTION_LABEL[group.key] || group.key}
            group={group}
            columns={columns}
            getRowRuntime={getRowRuntime}
            t={t}
          />
        ))}
      </div>
      {/* Global empty state — every section filtered out. Same actionable
          "Clear filters" affordance the table-level empty state carries. */}
      {sections.length === 0 && allModels.length > 0 && (
        <div className="flex items-center gap-2 px-[2px] py-[18px] text-sm text-muted-foreground">
          <span>{t('models.no_matches')}</span>
          <Button
            size="sm"
            variant="subtle"
            onClick={() => setQuery('')}
            data-testid="models-clear-filters"
          >
            {t('models.clear_filters')}
          </Button>
        </div>
      )}
    </section>
  );
}
