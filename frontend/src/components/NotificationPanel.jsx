/**
 * NotificationPanel — actionable notification center in the header.
 *
 * Polls GET /system/notifications on mount and every 30s.
 * Surfaces warnings (HF_TOKEN, ffmpeg, disk, GPU) with inline actions.
 * Allows setting HF_TOKEN directly from the panel.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Bell, AlertTriangle, AlertCircle, Info, ExternalLink, ChevronRight, Check } from 'lucide-react';
import { API } from '../api/client';
import './NotificationPanel.css';

const LEVEL_ICON = {
  warn:  <AlertTriangle size={11} />,
  error: <AlertCircle size={11} />,
  info:  <Info size={11} />,
};

export default function NotificationPanel({ onNavigate }) {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [dismissed, setDismissed] = useState(() => {
    try { return JSON.parse(localStorage.getItem('omni_notif_dismissed') || '[]'); }
    catch { return []; }
  });
  const [hfInput, setHfInput] = useState('');
  const [hfSaving, setHfSaving] = useState(false);
  const panelRef = useRef(null);

  const fetchNotifications = useCallback(async () => {
    try {
      const res = await fetch(`${API}/system/notifications`);
      if (res.ok) {
        const data = await res.json();
        setNotifications(data.notifications || []);
      }
    } catch {
      // Backend not ready yet
    }
  }, []);

  // Poll on mount + every 30s
  useEffect(() => {
    fetchNotifications();
    const iv = setInterval(fetchNotifications, 30000);
    return () => clearInterval(iv);
  }, [fetchNotifications]);

  // Click outside to close
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const visibleNotifs = notifications.filter(n => !dismissed.includes(n.id));
  const hasErrors = visibleNotifs.some(n => n.level === 'error');
  const hasWarns = visibleNotifs.some(n => n.level === 'warn');

  const dismiss = (id) => {
    const next = [...dismissed, id];
    setDismissed(next);
    localStorage.setItem('omni_notif_dismissed', JSON.stringify(next));
  };

  const dismissAll = () => {
    const next = notifications.map(n => n.id);
    setDismissed(next);
    localStorage.setItem('omni_notif_dismissed', JSON.stringify(next));
  };

  const handleAction = (notif) => {
    if (!notif.action) return;

    if (notif.action.type === 'navigate' && onNavigate) {
      onNavigate(notif.action.target);
      setOpen(false);
    } else if (notif.action.type === 'link') {
      window.open(notif.action.target, '_blank');
    }
  };

  const saveHfToken = async () => {
    if (!hfInput.trim()) return;
    setHfSaving(true);
    try {
      const res = await fetch(`${API}/system/set-env`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'HF_TOKEN', value: hfInput.trim() }),
      });
      if (res.ok) {
        dismiss('hf-token-missing');
        setHfInput('');
        // Re-fetch to reflect the change
        setTimeout(fetchNotifications, 500);
      }
    } catch (e) {
      console.warn('Failed to set HF_TOKEN:', e);
    } finally {
      setHfSaving(false);
    }
  };

  return (
    <div className="notif-wrap" ref={panelRef} style={{ position: 'relative' }}>
      {/* Bell trigger */}
      <button
        className={`notif-trigger ${visibleNotifs.length > 0 ? 'notif-trigger--has-items' : ''}`}
        onClick={() => setOpen(!open)}
        aria-label={`Notifications (${visibleNotifs.length})`}
        title="Notifications"
      >
        <Bell size={14} />
        {visibleNotifs.length > 0 && (
          <span className={`notif-badge ${hasErrors ? '' : hasWarns ? 'notif-badge--warn' : ''}`}>
            {visibleNotifs.length}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {open && (
        <div className="notif-panel" role="dialog" aria-label="Notifications">
          <div className="notif-panel__header">
            <h3 className="notif-panel__title">Notifications</h3>
            {visibleNotifs.length > 0 && (
              <button className="notif-panel__dismiss" onClick={dismissAll}>
                Dismiss all
              </button>
            )}
          </div>

          {visibleNotifs.length === 0 ? (
            <div className="notif-panel__empty">
              <div className="notif-panel__empty-icon">✅</div>
              All clear — no issues detected
            </div>
          ) : (
            visibleNotifs.map(notif => (
              <div key={notif.id} className="notif-item">
                <div className={`notif-item__icon notif-item__icon--${notif.level}`}>
                  {LEVEL_ICON[notif.level] || LEVEL_ICON.info}
                </div>
                <div className="notif-item__body">
                  <p className="notif-item__title">{notif.title}</p>
                  <p className="notif-item__message">{notif.message}</p>

                  {/* Special: inline HF_TOKEN input */}
                  {notif.id === 'hf-token-missing' && (
                    <div className="notif-hf-input">
                      <input
                        type="password"
                        placeholder="hf_xxxxxxxxxxxx"
                        value={hfInput}
                        onChange={e => setHfInput(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && saveHfToken()}
                        aria-label="HuggingFace token"
                      />
                      <button onClick={saveHfToken} disabled={hfSaving || !hfInput.trim()}>
                        {hfSaving ? '…' : 'Save'}
                      </button>
                    </div>
                  )}

                  {notif.action && notif.id !== 'hf-token-missing' && (
                    <button
                      className="notif-item__action"
                      onClick={() => handleAction(notif)}
                    >
                      {notif.action.label}
                      {notif.action.type === 'link' ? <ExternalLink size={10} /> : <ChevronRight size={10} />}
                    </button>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
