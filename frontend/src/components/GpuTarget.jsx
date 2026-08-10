/**
 * Header GPU picker — where the next job runs.
 *
 * Exactly one target is active at a time: this machine, or one worker you
 * enrolled. Other connected workers are standby and receive nothing.
 *
 * The badge shows the **resolved** answer, not the stored choice, and those
 * differ in the case that matters: you picked your desktop, your desktop went
 * to sleep, and the work is now running locally. Showing the choice there
 * would be a lie every time it mattered most — so the chip reads "Local" with
 * the reason underneath, while the menu still shows your desktop as selected.
 *
 * `Local` has no rename control. It is not a machine — it is this machine —
 * and there is nothing to name.
 */
import React, { useCallback, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Cpu, Check, ChevronDown } from 'lucide-react';
import toast from 'react-hot-toast';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../api/client';

// Two cadences: a slow tick that just keeps status honest, and a fast one
// while work is in flight so the task count reads as live rather than lagging
// several seconds behind the thing the user is watching.
const IDLE_REFRESH_MS = 5000;
const BUSY_REFRESH_MS = 1000;

/** ready → green, busy → amber, offline → red. */
const DOT = {
  ready: 'bg-emerald-400',
  busy: 'bg-amber-400',
  offline: 'bg-red-400',
};

function StatusDot({ status }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-[6px] w-[6px] shrink-0 rounded-full ${DOT[status] || DOT.offline}`}
    />
  );
}

/** Latency is only meaningful for a machine across a network. */
function latencyLabel(target) {
  if (!target || target.is_local || !target.connected) return '';
  const ms = target.latency_ms;
  // 0 means "not measured yet", not "instantaneous" — say nothing rather than
  // claim a suspiciously perfect link.
  if (!ms) return '';
  return ms < 1 ? '<1 ms' : `${Math.round(ms)} ms`;
}

async function request(path, { body, ...opts } = {}) {
  const res = await apiFetch(path, {
    ...opts,
    ...(body === undefined
      ? {}
      : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });
  const payload = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = payload?.detail;
    throw new Error(
      typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : `HTTP ${res.status}`,
    );
  }
  return payload;
}

export default function GpuTarget() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  // The header's status row is `overflow-hidden`, which clips an absolutely
  // positioned menu — the entries below the first simply vanish. Rendering
  // into a portal and positioning from the button's rect escapes the clip.
  const buttonRef = useRef(null);
  const [anchor, setAnchor] = useState(null);

  const toggle = useCallback(() => {
    setOpen((wasOpen) => {
      if (!wasOpen && buttonRef.current) {
        const rect = buttonRef.current.getBoundingClientRect();
        setAnchor({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
      }
      return !wasOpen;
    });
  }, []);

  const { data } = useQuery({
    queryKey: ['workers', 'target'],
    queryFn: () => request('/workers/target'),
    refetchInterval: (query) => {
      const t = (query.state?.data?.targets || []).find((x) => x.id === query.state?.data?.target);
      return t && t.active_tasks > 0 ? BUSY_REFRESH_MS : IDLE_REFRESH_MS;
    },
    refetchIntervalInBackground: false,
    retry: false,
  });

  const targets = data?.targets || [];
  const active = data?.active;
  const chosen = data?.target || 'local';

  // Nothing to choose between: with no worker enrolled, a GPU picker is just
  // clutter on a feature the user has not opted into.
  if (targets.length <= 1) return null;

  const chosenTarget = targets.find((x) => x.id === chosen);
  const activeTarget = active?.remote
    ? targets.find((x) => x.id === active.worker_id)
    : targets.find((x) => x.is_local);
  const label = active?.remote ? active.label : t('gpu.local', { defaultValue: 'Local' });
  const fellBack = !active?.remote && chosen !== 'local';
  // When the chosen worker is unreachable the work runs here, but the DOT must
  // report the worker's state — a green dot beside "Local" would hide that
  // the machine you picked is down.
  const dotStatus = fellBack ? chosenTarget?.status || 'offline' : activeTarget?.status || 'ready';
  const chipLatency = latencyLabel(active?.remote ? activeTarget : null);

  const choose = async (id) => {
    setOpen(false);
    try {
      const next = await request('/workers/target', { method: 'POST', body: { target: id } });
      queryClient.setQueryData(['workers', 'target'], next);
      queryClient.invalidateQueries({ queryKey: ['workers'] });
    } catch (e) {
      toast.error(e?.message || String(e));
    }
  };

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={toggle}
        title={active?.reason || undefined}
        aria-label={t('gpu.picker', { defaultValue: 'Where jobs run' })}
        className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs opacity-80 hover:opacity-100"
      >
        <Cpu size={13} />
        <StatusDot status={dotStatus} />
        <span className={fellBack ? 'text-amber-400' : undefined}>{label}</span>
        {chipLatency && <span className="opacity-60">{chipLatency}</span>}
        <ChevronDown size={11} />
      </button>

      {open &&
        anchor &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[9998]" onClick={() => setOpen(false)} />
            <div
              data-slot="gpu-target-menu"
              style={{ top: anchor.top, right: anchor.right }}
              className="fixed z-[9999] min-w-[240px] rounded-lg border border-transparent bg-[var(--chrome-bg)] p-1 shadow-lg" >
            {targets.map((target) => (
              // Any enrolled worker is selectable, including an offline one:
              // you pick your desktop and then go and switch it on. Routing
              // already falls back locally with a reason until it answers, so
              // forbidding the choice would only prevent setting it up.
              <button
                key={target.id}
                type="button"
                onClick={() => choose(target.id)}
                className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-white/5 ${
                  target.available ? '' : 'opacity-60'
                }`}
              >
                <span className="w-3">{target.id === chosen ? <Check size={12} /> : null}</span>
                {target.is_local ? (
                  <span className="w-[6px]" />
                ) : (
                  <StatusDot status={target.status} />
                )}
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate">{target.label}</span>
                    {latencyLabel(target) && (
                      <span className="shrink-0 opacity-60">{latencyLabel(target)}</span>
                    )}
                  </span>
                  {/* The address disambiguates two machines a user named
                      similarly; the detail says why one cannot be picked; the
                      task count is what makes "busy" mean something. */}
                  {!target.is_local && (
                    <span className="block truncate opacity-60">
                      {target.detail
                        ? target.detail
                        : target.active_tasks > 0
                          ? `${target.endpoint} · ${target.active_tasks}/${target.max_tasks} ${t(
                              'gpu.tasks',
                              { defaultValue: 'tasks' },
                            )}`
                          : target.endpoint}
                    </span>
                  )}
                </span>
              </button>
            ))}
            {fellBack && active?.reason && (
              <p className="m-0 px-2 py-1 text-[11px] text-amber-400">{active.reason}</p>
            )}
            </div>
          </>,
          document.body,
        )}
    </div>
  );
}
