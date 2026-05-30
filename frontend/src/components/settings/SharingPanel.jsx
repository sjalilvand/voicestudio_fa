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
import QRCode from 'qrcode';
import { Wifi, Globe, Copy, ExternalLink } from 'lucide-react';
import toast from 'react-hot-toast';
import { apiJson, apiPost } from '../../api/client';
import { openExternal } from '../../api/external';
import NetworkToggle from '../NetworkToggle';
import './SharingPanel.css';

const TAILSCALE_DOWNLOAD_URL = 'https://tailscale.com/download';

export default function SharingPanel() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState('');
  const [note, setNote] = useState('');
  const [qr, setQr] = useState('');

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
        toast.success('Tailscale serve enabled');
        await refresh();
      } else {
        toast.error(r?.error || 'Could not enable Tailscale');
      }
    } catch (e) {
      toast.error(`Could not enable Tailscale: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    try {
      const r = await apiPost('/system/tailscale/disable');
      if (r && r.ok === false) {
        toast.error(r.error || 'Could not disable Tailscale');
      } else {
        setUrl('');
        setNote('');
        toast.success('Tailscale serve disabled');
      }
      await refresh();
    } catch (e) {
      toast.error(`Could not disable Tailscale: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const copy = (text) => { navigator.clipboard?.writeText(text); toast.success('Copied'); };

  const installed = !!status?.installed;
  const running = !!status?.running;

  return (
    <section className="sharingpanel" aria-labelledby="sharingpanel-heading">
      <h3 id="sharingpanel-heading" className="sharingpanel__title">
        <Wifi size={14} /> Sharing &amp; Remote Access
      </h3>

      <p className="sharingpanel__help">
        Expose this running OmniVoice instance to your other machines without
        restarting it. Loopback-only is the default — nothing is shared until
        you turn it on here.
      </p>

      {/* ── LAN sharing ──────────────────────────────────────────────── */}
      <div className="sharingpanel__section" data-testid="sharing-lan">
        <h4 className="sharingpanel__subtitle">
          <Wifi size={12} /> Local network
        </h4>
        <p className="sharingpanel__subhelp">
          Share on your Wi-Fi / Ethernet with a one-time access PIN. Other
          devices scan the QR code or open the link.
        </p>
        <NetworkToggle />
      </div>

      {/* ── Tailscale ────────────────────────────────────────────────── */}
      <div className="sharingpanel__section" data-testid="sharing-tailscale">
        <h4 className="sharingpanel__subtitle">
          <Globe size={12} /> Tailscale (private remote access)
        </h4>

        {loading && !status && (
          <p className="sharingpanel__subhelp">Checking for Tailscale…</p>
        )}

        {status && !installed && (
          <div className="sharingpanel__tailscale-absent" data-testid="tailscale-absent">
            <p className="sharingpanel__subhelp">
              Tailscale not detected. Install it to reach OmniVoice securely
              from anywhere on your private tailnet.
            </p>
            <button
              type="button"
              className="sharingpanel__btn"
              onClick={() => openExternal(TAILSCALE_DOWNLOAD_URL)}
              data-testid="tailscale-install"
            >
              <ExternalLink size={12} /> Install Tailscale
            </button>
          </div>
        )}

        {status && installed && (
          <div className="sharingpanel__tailscale-present">
            <p className="sharingpanel__subhelp">
              {running
                ? 'Tailscale is running. Serve OmniVoice over your private tailnet.'
                : 'Tailscale is installed but not logged in. Start and sign in to Tailscale first.'}
            </p>

            {!url ? (
              <button
                type="button"
                className="sharingpanel__btn"
                onClick={enable}
                disabled={busy}
                data-testid="tailscale-enable"
              >
                {busy ? 'Enabling…' : 'Enable Tailscale serve'}
              </button>
            ) : (
              <div className="sharingpanel__tailscale-url">
                <div className="sharingpanel__row">
                  <code className="sharingpanel__addr">{url}</code>
                  <button
                    type="button"
                    className="sharingpanel__iconbtn"
                    onClick={() => copy(url)}
                    aria-label="Copy Tailscale URL"
                    title="Copy link"
                    data-testid="tailscale-copy"
                  >
                    <Copy size={12} />
                  </button>
                  <button
                    type="button"
                    className="sharingpanel__iconbtn"
                    onClick={() => openExternal(url)}
                    aria-label="Open Tailscale URL"
                    title="Open in browser"
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
                    alt="QR code for the Tailscale URL"
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
                  {busy ? 'Disabling…' : 'Stop Tailscale serve'}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
