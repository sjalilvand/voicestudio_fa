/**
 * Settings → Sharing & Remote Access panel.
 *
 * Surfaces the two ways to reach this running backend from another machine,
 * without restarting it:
 *   - LAN sharing (PIN + QR) — reuses the footer <NetworkToggle/> control so
 *     there is a single source of truth for the /system/network/* endpoints.
 *   - Tailscale private remote access — drives the loopback-only
 *     /system/tailscale/{status,enable,disable} endpoints.
 *
 * Loopback-only stays the default; nothing here changes that until the user
 * explicitly enables a share.
 *
 * Endpoints:
 *   GET  /system/tailscale/status   → {installed, running, magic_dns_name, tailnet_ips}
 *   POST /system/tailscale/enable   → {ok, url} | {ok:false, error}
 *   POST /system/tailscale/disable  → {ok}
 */
import React, { useCallback, useEffect, useState } from 'react';
import { copyText } from "../../utils/copyText";
import QRCode from 'qrcode';
import { Wifi, Globe, Copy, ExternalLink } from 'lucide-react';
import toast from 'react-hot-toast';
import { useTranslation } from 'react-i18next';
import { apiJson, apiPost } from '../../api/client';
import { openExternal } from '../../api/external';
import NetworkToggle from '../NetworkToggle';
import './SharingPanel.css';

const TAILSCALE_DOWNLOAD_URL = 'https://tailscale.com/download';

export default function SharingPanel() {
  const { t } = useTranslation();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState('');
  const [note, setNote] = useState('');
  const [qr, setQr] = useState('');
  // Port configuration (read from /system/info; LAN-share port is editable).
  const [ports, setPorts] = useState(null);
  const [sharePortInput, setSharePortInput] = useState('');
  const [savingPort, setSavingPort] = useState(false);

  // Fetch the resolved port config once on mount; cancel-safe.
  useEffect(() => {
    const ctrl = { aborted: false };
    (async () => {
      try {
        const info = await apiJson('/system/info');
        if (ctrl.aborted) return;
        setPorts(info);
        if (info?.share_port_base != null) {
          setSharePortInput(String(info.share_port_base));
        }
      } catch {
        // Loopback-only; if unreachable just hide the ports subsection.
        if (!ctrl.aborted) setPorts(null);
      }
    })();
    return () => { ctrl.aborted = true; };
  }, []);

  const saveSharePort = async () => {
    const n = Number(sharePortInput);
    if (!Number.isInteger(n) || n < 1024 || n > 65535) {
      toast.error(t('sharing.port_error'));
      return;
    }
    setSavingPort(true);
    try {
      await apiPost('/system/set-env', { key: 'OMNIVOICE_SHARE_PORT', value: String(n) });
      setPorts((p) => (p ? { ...p, share_port_base: n } : p));
      toast.success(t('sharing.port_saved'));
    } catch (e) {
      toast.error(t('sharing.port_save_failed', { message: e.message }));
    } finally {
      setSavingPort(false);
    }
  };

  const refresh = useCallback(async (signal) => {
    setLoading(true);
    try {
      const s = await apiJson('/system/tailscale/status');
      if (signal?.aborted) return;
      setStatus(s);
    } catch {
      // Loopback-only control surface; if it can't be reached, treat as absent.
      if (!signal?.aborted) setStatus({ installed: false });
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  // Fetch Tailscale status once on mount; cancel-safe.
  useEffect(() => {
    const ctrl = { aborted: false };
    refresh(ctrl);
    return () => { ctrl.aborted = true; };
  }, [refresh]);

  // Render a QR for the Tailscale URL when one is available; cancel-safe.
  useEffect(() => {
    if (!url) { setQr(''); return; }
    let cancelled = false;
    (async () => {
      try {
        const data = await QRCode.toDataURL(url);
        if (!cancelled) setQr(data);
      } catch {
        if (!cancelled) setQr('');
      }
    })();
    return () => { cancelled = true; };
  }, [url]);

  const enable = async () => {
    setBusy(true);
    try {
      const r = await apiPost('/system/tailscale/enable');
      if (r?.ok) {
        setUrl(r.url || '');
        setNote(r.note || '');
        toast.success(t('sharing.tailscale_enabled'));
        await refresh();
      } else {
        toast.error(r?.error || t('sharing.tailscale_enable_failed'));
      }
    } catch (e) {
      toast.error(t('sharing.tailscale_enable_error', { message: e.message }));
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    try {
      const r = await apiPost('/system/tailscale/disable');
      if (r && r.ok === false) {
        toast.error(r.error || t('sharing.tailscale_disable_failed'));
      } else {
        setUrl('');
        setNote('');
        toast.success(t('sharing.tailscale_disabled'));
      }
      await refresh();
    } catch (e) {
      toast.error(t('sharing.tailscale_disable_error', { message: e.message }));
    } finally {
      setBusy(false);
    }
  };

  const copy = (text) => { copyText(text); toast.success(t('sharing.copied')); };

  const installed = !!status?.installed;
  const running = !!status?.running;

  return (
    <section className="sharingpanel" aria-labelledby="sharingpanel-heading">
      <h3 id="sharingpanel-heading" className="sharingpanel__title">
        <Wifi size={14} /> {t('sharing.title')}
      </h3>

      <p className="sharingpanel__help">
        {t('sharing.help')}
      </p>

      {/* ── LAN sharing ──────────────────────────────────────────────── */}
      <div className="sharingpanel__section" data-testid="sharing-lan">
        <h4 className="sharingpanel__subtitle">
          <Wifi size={12} /> {t('sharing.local_network')}
        </h4>
        <p className="sharingpanel__subhelp">
          {t('sharing.local_help')}
        </p>
        <NetworkToggle />
      </div>

      {/* ── Ports ────────────────────────────────────────────────────── */}
      {ports && (
        <div className="sharingpanel__section" data-testid="sharing-ports">
          <h4 className="sharingpanel__subtitle">
            <Globe size={12} /> {t('sharing.ports_title')}
          </h4>
          <p className="sharingpanel__subhelp">
            {t('sharing.ports_help')}
          </p>

          <div className="sharingpanel__row">
            <span>{t('sharing.backend_port')}</span>
            <code className="sharingpanel__addr" data-testid="port-backend">{ports.backend_port}</code>
            <code className="sharingpanel__envname">OMNIVOICE_PORT</code>
          </div>

          <div className="sharingpanel__row">
            <span>{t('sharing.ui_port')}</span>
            <code className="sharingpanel__addr" data-testid="port-ui">{ports.ui_port}</code>
            <code className="sharingpanel__envname">OMNIVOICE_UI_PORT</code>
          </div>

          <div className="sharingpanel__row">
            <label htmlFor="share-port-input">{t('sharing.lan_share_port')}</label>
            <input
              id="share-port-input"
              type="number"
              min={1024}
              max={65535}
              value={sharePortInput}
              onChange={(e) => setSharePortInput(e.target.value)}
              className="sharingpanel__portinput"
              data-testid="port-share-input"
            />
            <code className="sharingpanel__envname">OMNIVOICE_SHARE_PORT</code>
            <button
              type="button"
              className="sharingpanel__btn"
              onClick={saveSharePort}
              disabled={savingPort}
              data-testid="port-share-save"
            >
              {savingPort ? t('sharing.saving') : t('common.save')}
            </button>
          </div>
          <p className="sharingpanel__note">
            {t('sharing.ports_note')}
          </p>
        </div>
      )}

      {/* ── Tailscale ────────────────────────────────────────────────── */}
      <div className="sharingpanel__section" data-testid="sharing-tailscale">
        <h4 className="sharingpanel__subtitle">
          <Globe size={12} /> {t('sharing.tailscale_title')}
        </h4>

        {loading && !status && (
          <p className="sharingpanel__subhelp">{t('sharing.tailscale_checking')}</p>
        )}

        {status && !installed && (
          <div className="sharingpanel__tailscale-absent" data-testid="tailscale-absent">
            <p className="sharingpanel__subhelp">
              {t('sharing.tailscale_absent')}
            </p>
            <button
              type="button"
              className="sharingpanel__btn"
              onClick={() => openExternal(TAILSCALE_DOWNLOAD_URL)}
              data-testid="tailscale-install"
            >
              <ExternalLink size={12} /> {t('sharing.tailscale_install')}
            </button>
          </div>
        )}

        {status && installed && (
          <div className="sharingpanel__tailscale-present">
            <p className="sharingpanel__subhelp">
              {running
                ? t('sharing.tailscale_running')
                : t('sharing.tailscale_not_logged_in')}
            </p>

            {!url ? (
              <button
                type="button"
                className="sharingpanel__btn"
                onClick={enable}
                disabled={busy}
                data-testid="tailscale-enable"
              >
                {busy ? t('sharing.tailscale_enabling') : t('sharing.tailscale_enable_btn')}
              </button>
            ) : (
              <div className="sharingpanel__tailscale-url">
                <div className="sharingpanel__row">
                  <code className="sharingpanel__addr">{url}</code>
                  <button
                    type="button"
                    className="sharingpanel__iconbtn"
                    onClick={() => copy(url)}
                    aria-label={t('sharing.tailscale_copy')}
                    title={t('sharing.tailscale_copy')}
                    data-testid="tailscale-copy"
                  >
                    <Copy size={12} />
                  </button>
                  <button
                    type="button"
                    className="sharingpanel__iconbtn"
                    onClick={() => openExternal(url)}
                    aria-label={t('sharing.tailscale_open')}
                    title={t('sharing.tailscale_open')}
                    data-testid="tailscale-open"
                  >
                    <ExternalLink size={12} />
                  </button>
                </div>
                {note && <p className="sharingpanel__note" data-testid="tailscale-note">{note}</p>}
                {qr && (
                  <img
                    className="sharingpanel__qr"
                    src={qr}
                    alt={t('sharing.tailscale_qr_alt')}
                    width={104}
                    height={104}
                  />
                )}
                <button
                  type="button"
                  className="sharingpanel__btn sharingpanel__btn--ghost"
                  onClick={disable}
                  disabled={busy}
                  data-testid="tailscale-disable"
                >
                  {busy ? t('sharing.tailscale_disabling') : t('sharing.tailscale_disable_btn')}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
