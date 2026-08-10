/**
 * Settings → System → Remote workers.
 *
 * Run inference on your other machines. Its own System entry rather than a
 * section under Sharing, because the direction is opposite: everything in
 * Sharing is about letting something else reach THIS machine, while this
 * sends work OUT to machines you own and brings the results back.
 *
 * Also distinct from the Remote backend panel under Sharing: that one points
 * this app at a backend running elsewhere, so the work and the data both live
 * there. This keeps the app here and hands out individual tasks.
 *
 * Two rules the UI must not soften, because they are the feature's contract:
 *
 *   • Off means off. With the toggle off there is no listening socket, no
 *     certificate, and no background loop — the app is what it was before.
 *   • Every worker is consented to individually. Audio, reference voices, and
 *     text leave this machine for a worker, so "I trust my desktop" is not
 *     "I trust whatever else gets added later".
 *
 * The enrollment token is shown exactly once. Only its hash is stored, so
 * there is no way to display it again — that is the point, not a limitation.
 */
import React, { useState } from 'react';
import { Cpu, Copy, Check, Trash2, PlayCircle, Pencil } from 'lucide-react';
import toast from 'react-hot-toast';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';
import { askConfirm } from '../../utils/dialog';
import { SettingsSection, SettingRow, SettingsToggle } from './primitives';
import { Button, Badge } from '../../ui';

const REFRESH_MS = 5000;

/**
 * `apiFetch` deliberately returns the raw Response and sets no Content-Type —
 * it preserves the call shape so FormData posts keep working. Every JSON
 * caller therefore has to say so itself and parse the body, and a non-2xx is
 * NOT an exception, so an unchecked call fails silently.
 *
 * This wrapper does all three in one place, and surfaces FastAPI's `detail`
 * so the user sees "Remote workers are turned off…" instead of "500".
 */
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

export default function WorkersPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [token, setToken] = useState(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  const { data } = useQuery({
    queryKey: ['workers'],
    queryFn: () => request('/workers'),
    // Only poll once the feature is on: a disabled panel should not generate
    // background traffic every five seconds forever.
    refetchInterval: (query) => (query.state?.data?.running ? REFRESH_MS : false),
    refetchIntervalInBackground: false,
  });

  const enabled = Boolean(data?.enabled);
  const workers = data?.workers || [];

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['workers'] });

  const setEnabled = async (next) => {
    setBusy(true);
    try {
      await request('/workers/enabled', { method: 'POST', body: { enabled: next } });
      if (!next) setToken(null);
      refresh();
    } catch (e) {
      toast.error(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const createToken = async () => {
    setBusy(true);
    setCopied(false);
    try {
      setToken(await request('/workers/enrollments', { method: 'POST', body: { ttl_seconds: 900 } }));
    } catch (e) {
      toast.error(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const copyToken = async () => {
    try {
      await navigator.clipboard.writeText(token.token);
      setCopied(true);
    } catch {
      toast.error(t('settings.workers_copy_failed', { defaultValue: 'Could not copy.' }));
    }
  };

  const removeWorker = async (worker) => {
    const ok = await askConfirm(
      t('settings.workers_remove_confirm', {
        name: worker.name,
        defaultValue:
          'Remove {{name}}? Its key is revoked, so it cannot reconnect without a new token.',
      }),
      t('settings.workers_remove_title', { defaultValue: 'Remove worker?' }),
    );
    if (!ok) return;
    try {
      await request(`/workers/${worker.id}`, { method: 'DELETE' });
      refresh();
    } catch (e) {
      toast.error(e?.message || String(e));
    }
  };

  const resumeWorker = async (worker) => {
    try {
      await request(`/workers/${worker.id}/resume`, { method: 'POST' });
      refresh();
    } catch (e) {
      toast.error(e?.message || String(e));
    }
  };

  const renameWorker = async (worker, name) => {
    const trimmed = (name || '').trim();
    // An empty name would leave the row labelled by its key id, which is not
    // something a user can recognise — treat it as "keep the current name".
    if (!trimmed || trimmed === worker.name) return;
    try {
      await request(`/workers/${worker.id}`, { method: 'PATCH', body: { name: trimmed } });
      refresh();
    } catch (e) {
      toast.error(e?.message || String(e));
    }
  };

  const toggleWorker = async (worker) => {
    try {
      await request(`/workers/${worker.id}`, {
        method: 'PATCH',
        body: { enabled: !worker.enabled },
      });
      refresh();
    } catch (e) {
      toast.error(e?.message || String(e));
    }
  };

  return (
    <SettingsSection
      icon={Cpu}
      title={t('settings.workers_title', { defaultValue: 'Remote workers' })}
      description={t('settings.workers_desc', {
        defaultValue:
          'Send individual jobs to GPUs on your other machines. Results come back here. Nothing is sent until you add a worker and approve it.',
      })}
    >
      <SettingRow
        title={t('settings.workers_enable', { defaultValue: 'Use remote workers' })}
        subtitle={t('settings.workers_enable_hint', {
          defaultValue:
            'While this is off, no connection is accepted and nothing leaves this machine.',
        })}
        control={<SettingsToggle checked={enabled} disabled={busy} onChange={setEnabled} />}
      />

      {enabled && (
        <>
          <SettingRow
            mono
            title={t('settings.workers_endpoint', { defaultValue: 'Workers connect to' })}
            subtitle={t('settings.workers_endpoint_hint', {
              defaultValue:
                'A worker has to be able to reach this address. On different networks, a VPN such as Tailscale is the reliable way.',
            })}
            control={<code>{data?.endpoint || '—'}</code>}
          />

          <SettingRow
            title={t('settings.workers_add', { defaultValue: 'Add a worker' })}
            subtitle={t('settings.workers_add_hint', {
              defaultValue:
                'Generate a token, then paste it into OmniVoice on the other machine.',
            })}
            control={
              <Button onClick={createToken} disabled={busy}>
                {t('settings.workers_new_token', { defaultValue: 'Generate token' })}
              </Button>
            }
          />

          {token && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
              {/* Deliberately plain visible text, not an InfoHint tooltip: a
                  warning the user must act on before navigating away cannot
                  be hidden behind a hover. */}
              <p className="m-0 text-xs text-amber-300">
                {t('settings.workers_token_once', {
                  defaultValue:
                    'Copy this now — it is shown only once, works only once, and expires in 15 minutes.',
                })}
              </p>
              <div className="mt-2 flex items-center gap-2">
                <code className="flex-1 break-all rounded bg-black/20 p-2 text-xs">
                  {token.token}
                </code>
                <Button variant="secondary" onClick={copyToken}>
                  {copied ? <Check size={14} /> : <Copy size={14} />}
                  {copied
                    ? t('settings.workers_copied', { defaultValue: 'Copied' })
                    : t('settings.workers_copy', { defaultValue: 'Copy' })}
                </Button>
              </div>
            </div>
          )}

          {workers.length === 0 ? (
            <p className="py-3 text-sm opacity-70">
              {t('settings.workers_none', {
                defaultValue: 'No workers yet. Generate a token to add your first one.',
              })}
            </p>
          ) : (
            <ul className="divide-y divide-white/10">
              {workers.map((w) => (
                <WorkerRow
                  key={w.id}
                  worker={w}
                  onRemove={() => removeWorker(w)}
                  onResume={() => resumeWorker(w)}
                  onToggle={() => toggleWorker(w)}
                  onRename={(name) => renameWorker(w, name)}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </SettingsSection>
  );
}

export function WorkerRow({ worker, onRemove, onResume, onToggle, onRename = () => {} }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(worker.name);
  const paused = (worker.breakers || []).length > 0;

  const commit = () => {
    setEditing(false);
    onRename(draft);
  };
  const status = !worker.enabled
    ? t('settings.workers_status_disabled', { defaultValue: 'Disabled' })
    : paused
      ? t('settings.workers_status_paused', { defaultValue: 'Paused' })
      : worker.connected
        ? t('settings.workers_status_online', { defaultValue: 'Online' })
        : t('settings.workers_status_offline', { defaultValue: 'Offline' });

  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {editing ? (
            <input
              autoFocus
              aria-label={t('settings.workers_rename', { defaultValue: 'Rename worker' })}
              className="min-w-0 flex-1 rounded bg-black/20 px-2 py-0.5 text-sm"
              value={draft}
              maxLength={120}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commit();
                if (e.key === 'Escape') {
                  setDraft(worker.name);
                  setEditing(false);
                }
              }}
            />
          ) : (
            <>
              <span className="truncate font-medium">{worker.name}</span>
              <button
                type="button"
                className="opacity-60 hover:opacity-100"
                aria-label={t('settings.workers_rename', { defaultValue: 'Rename worker' })}
                onClick={() => {
                  setDraft(worker.name);
                  setEditing(true);
                }}
              >
                <Pencil size={12} />
              </button>
            </>
          )}
          <Badge tone={worker.connected && worker.enabled && !paused ? 'success' : 'neutral'}>
            {status}
          </Badge>
          {!worker.consent_granted && (
            <Badge tone="warning">
              {t('settings.workers_needs_consent', { defaultValue: 'Not approved' })}
            </Badge>
          )}
        </div>
        {worker.connected && (
          <p className="mt-0.5 text-xs opacity-70">
            {t('settings.workers_load', {
              active: worker.active_tasks ?? 0,
              slots: (worker.active_tasks ?? 0) + (worker.available_slots ?? 0),
              defaultValue: 'Tasks {{active}} / {{slots}}',
            })}
          </p>
        )}
        {/* The breaker summary is written to be understood: "paused after 3
            failures, retrying in 60s" is actionable in a way that a
            reliability percentage never is. */}
        {paused && (
          <p className="mt-0.5 text-xs text-amber-400">{worker.breakers[0].summary}</p>
        )}
      </div>
      {paused && (
        <Button variant="secondary" size="sm" onClick={onResume}>
          <PlayCircle size={14} />
          {t('settings.workers_resume', { defaultValue: 'Resume' })}
        </Button>
      )}
      <Button variant="secondary" size="sm" onClick={onToggle}>
        {worker.enabled
          ? t('settings.workers_disable', { defaultValue: 'Disable' })
          : t('settings.workers_enable_one', { defaultValue: 'Enable' })}
      </Button>
      <Button variant="danger" size="sm" onClick={onRemove}>
        <Trash2 size={14} />
        {t('settings.workers_remove', { defaultValue: 'Remove' })}
      </Button>
    </li>
  );
}
