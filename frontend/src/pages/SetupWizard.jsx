import React, { useCallback, useEffect, useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CheckCircle, Loader, ArrowRight, AlertTriangle, XCircle,
  RefreshCw, Monitor, Download, Cog, FolderOpen,
} from 'lucide-react';
import { Button } from '../ui';
import { useSetupStatus, usePreflight } from '../api/hooks';
import { ModelStoreTab, EnginesTab } from './Settings';
import DictationDemo from '../components/DictationDemo';
import './SetupWizard.css';
import '../components/Misc.css';

// macOS convention: double-click the title-bar drag region to toggle zoom.
const doubleClickMaximize = async () => {
  try {
    if (!('__TAURI_INTERNALS__' in window)) return;
    const { getCurrentWindow } = await import('@tauri-apps/api/window');
    getCurrentWindow().toggleMaximize();
  } catch { /* non-tauri preview — ignore */ }
};

/** Shorten an absolute path for display: /Users/foo/.cache/x → ~/.cache/x */
function shortenPath(p) {
  if (!p) return '~/.cache/huggingface';
  try {
    const home = p.match(/^(\/Users\/[^/]+|\/home\/[^/]+|C:\\Users\\[^\\]+)/)?.[0];
    if (home) return p.replace(home, '~');
  } catch { /* fallthrough */ }
  return p;
}

/** Open a path in the OS file manager (Tauri only, no-op on web). */
async function revealPath(path) {
  try {
    if (!('__TAURI_INTERNALS__' in window)) return;
    const { revealItemInDir } = await import('@tauri-apps/plugin-opener');
    await revealItemInDir(path);
  } catch { /* ignore — probably web preview */ }
}

const CHECK_ICON = {
  pass: <CheckCircle size={13} />,
  warn: <AlertTriangle size={13} />,
  fail: <XCircle size={13} />,
};

/* ── Preflight panel ───────────────────────────────────────────────────── */

function PreflightPanel({ report, loading, onRecheck }) {
  const { t } = useTranslation();
  if (loading && !report) {
    return (
      <div className="swiz-loading">
        <Loader className="spinner" size={14} /> {t('setup.probing')}
      </div>
    );
  }
  if (!report) return null;
  return (
    <div className="swiz-checklist">
      <div className="swiz-check-header">
        <span className="swiz-check-header__label">{t('setup.system_preflight')}</span>
        <Button variant="ghost" size="sm" onClick={onRecheck} leading={<RefreshCw size={12} />}>
          {t('setup.recheck')}
        </Button>
      </div>
      {report.checks.map((c) => (
        <div key={c.id} className="setup-wizard__row swiz-check-row" style={{ alignItems: 'flex-start', padding: '8px 4px' }}>
          <span className={`swiz-check-icon swiz-check-icon--${c.status}`}>
            {CHECK_ICON[c.status] || null}
          </span>
          <div className="setup-wizard__row-body">
            <span className="setup-wizard__row-title">{c.label}</span>
            <span className="setup-wizard__muted" style={{ whiteSpace: 'normal' }}>{c.detail}</span>
            {c.fix && c.status !== 'pass' && (
              <span className="setup-wizard__muted" style={{
                color: c.status === 'fail' ? 'var(--color-danger)' : 'var(--color-warn, #fabd2f)',
                marginTop: 2,
                whiteSpace: 'normal',
              }}>
                → {c.fix}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Stepper nav with connectors ───────────────────────────────────────── */

function StepperNav({ step, onStep }) {
  const { t } = useTranslation();
  const stepLabels = [t('setup.welcome'), t('setup.system_check'), t('setup.install_models'), t('setup.pick_engines'), t('setup.try_dictation')];
  return (
    <div className="setup-wizard__steps" data-tauri-drag-region>
      {stepLabels.map((label, i) => (
        <React.Fragment key={label}>
          {i > 0 && (
            <span className={`setup-wizard__step-connector${step > i - 1 ? ' setup-wizard__step-connector--done' : ''}`} />
          )}
          <button
            className={[
              'setup-wizard__step',
              step === i ? 'setup-wizard__step--active' : '',
              step > i ? 'setup-wizard__step--done' : '',
            ].filter(Boolean).join(' ')}
            onClick={() => onStep(i)}
            type="button"
            aria-current={step === i ? 'step' : undefined}
            aria-label={`Step ${i + 1}: ${label}${step > i ? ' (completed)' : ''}`}
          >
            {step > i ? '✓ ' : `${i + 1}. `}{label}
          </button>
        </React.Fragment>
      ))}
    </div>
  );
}

/* ── Main wizard component ─────────────────────────────────────────────── */

/**
 * First-run / "no models installed" gate.
 *
 * Flow:
 *   0. Welcome    — hero + explainer + "continue"
 *   1. System     — /setup/preflight results
 *   2. Models     — ModelStoreTab, unlocks on models_ready
 *   3. Engines    — EnginesTab + "Enter studio"
 */
export default function SetupWizard({ onReady }) {
  const { t } = useTranslation();
  const [step, setStep] = useState(0);

  // TanStack Query — shared cache, auto-refetch on step 2 (models)
  const setupQuery = useSetupStatus();
  const preQuery   = usePreflight();
  const status     = setupQuery.data ?? null;
  const pre        = preQuery.data ?? null;
  const preLoading = preQuery.isLoading;

  // Poll setup status every 4s while on Models step
  useEffect(() => {
    if (step !== 2) return;
    const iv = setInterval(() => setupQuery.refetch(), 4000);
    return () => clearInterval(iv);
  }, [step, setupQuery]);

  const recheckPreflight = useCallback(() => { preQuery.refetch(); }, [preQuery]);

  const modelsReady = !!status?.models_ready;
  const preflightOk = !!pre?.ok;

  const cachePath = status?.hf_cache_dir || '~/.cache/huggingface';

  const WELCOME_CARDS = [
    {
      icon: <Monitor size={16} />,
      title: t('setup.system_check'),
      desc: t('setup.system_check_desc'),
    },
    {
      icon: <Download size={16} />,
      title: t('setup.install_models'),
      desc: t('setup.install_models_desc'),
    },
    {
      icon: <Cog size={16} />,
      title: t('setup.pick_engines'),
      desc: t('setup.pick_engines_desc'),
    },
  ];

  return (
    <div className="setup-wizard">
      <StepperNav step={step} onStep={setStep} />

      <div
        data-tauri-drag-region
        onDoubleClick={doubleClickMaximize}
        className="setup-wizard__hero"
      >
        <img src="/favicon.svg" alt="" className="setup-wizard__logo" />
        <div className="setup-wizard__hero-text">
          <h1 data-tauri-drag-region>OmniVoice Studio</h1>
          <span className="setup-wizard__sub" data-tauri-drag-region>
            {t('setup.hero_desc')}
          </span>
        </div>
      </div>

      {/* 0. Welcome */}
      {step === 0 && (
        <div className="swiz-slide" key="step-0">
          <div className="setup-wizard__embed">
            <div className="setup-wizard__welcome">
              <div className="setup-wizard__welcome-grid">
                {WELCOME_CARDS.map((card, i) => (
                  <div className="swiz-welcome-card" key={i}>
                    <div className="swiz-welcome-card__icon">{card.icon}</div>
                    <div className="swiz-welcome-card__body">
                      <span className="swiz-welcome-card__title">{card.title}</span>
                      <p className="swiz-welcome-card__desc">{card.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
              <p className="swiz-welcome-note">
                {t('setup.first_run')}
              </p>
            </div>
          </div>
          <div className="setup-wizard__nav">
            <span />
            <Button
              variant="primary" size="sm"
              onClick={() => setStep(1)}
              trailing={<ArrowRight size={14} />}
            >
              {t('setup.get_started')}
            </Button>
          </div>
        </div>
      )}

      {/* 1. System check */}
      {step === 1 && (
        <div className="swiz-slide" key="step-1">
          <div className="setup-wizard__embed">
            <PreflightPanel report={pre} loading={preLoading} onRecheck={recheckPreflight} />
          </div>
          <div className="setup-wizard__nav">
            <Button variant="ghost" onClick={() => setStep(0)}>{t('setup.back')}</Button>
            <Button
              variant={preflightOk ? 'primary' : 'ghost'}
              onClick={() => setStep(2)}
              trailing={<ArrowRight size={14} />}
              disabled={!preflightOk}
              title={preflightOk ? '' : t('setup.resolve_blockers')}
            >
              {preflightOk
                ? (pre?.has_warnings ? t('setup.continue_warn') : t('setup.continue_ok'))
                : t('setup.continue_blocked')}
            </Button>
          </div>
        </div>
      )}

      {/* 2. Models */}
      {step === 2 && (
        <div className="swiz-slide" key="step-2">
          <div className="setup-wizard__embed">
            <ModelStoreTab info={null} modelBadge={null} />
            {!modelsReady && status?.missing?.length > 0 && (
              <p className="setup-wizard__muted swiz-missing" style={{ marginTop: 8 }}>
                {t('setup.still_needed')}{' '}
                {status.missing.map(m => m.label).join(', ')}
              </p>
            )}
          </div>
          <div className="setup-wizard__nav">
            <Button variant="ghost" onClick={() => setStep(1)}>{t('setup.back')}</Button>
            <Button
              variant={modelsReady ? 'primary' : 'ghost'}
              onClick={() => setStep(3)}
              trailing={<ArrowRight size={14} />}
              disabled={!modelsReady}
              title={modelsReady ? '' : t('setup.install_required_models')}
            >
              {modelsReady
                ? t('setup.models_ready')
                : t('setup.waiting_models')}
            </Button>
          </div>
        </div>
      )}

      {/* 3. Engines */}
      {step === 3 && (
        <div className="swiz-slide" key="step-3">
          <div className="setup-wizard__embed">
            <EnginesTab />
          </div>
          <div className="setup-wizard__nav">
            <Button variant="ghost" onClick={() => setStep(2)}>{t('setup.back')}</Button>
            <Button
              variant="primary"
              onClick={() => setStep(4)}
              leading={<CheckCircle size={14} />}
            >
              {t('setup.next_try_dictation')}
            </Button>
          </div>
        </div>
      )}

      {/* 4. Dictation — guided walkthrough. Skippable (per cross-platform
          parity rule: some users genuinely don't want dictation). */}
      {step === 4 && (
        <div className="swiz-slide" key="step-4">
          <div className="setup-wizard__embed">
            <DictationDemo />
          </div>
          <div className="setup-wizard__nav">
            <Button variant="ghost" onClick={() => setStep(3)}>Back</Button>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button variant="subtle" onClick={onReady}>Skip</Button>
              <Button
                variant="primary"
                onClick={onReady}
                leading={<CheckCircle size={14} />}
              >
                Enter studio
              </Button>
            </div>
          </div>
        </div>
      )}

      {!status && step > 1 && (
        <div className="swiz-status-loading">
          <Loader className="spinner" size={14} /> {t('setup.checking')}
        </div>
      )}

      <p className="setup-wizard__footnote">
        {t('setup.footer_downloads')} <code>huggingface.co</code>
        <span style={{ margin: '0 2px' }}>·</span>
        Cache: <code>{shortenPath(cachePath)}</code>
        {'__TAURI_INTERNALS__' in window && cachePath && (
          <button
            className="setup-wizard__footnote-link"
            onClick={() => revealPath(cachePath)}
            title={t('setup.open_finder')}
          >
            <FolderOpen size={10} style={{ verticalAlign: '-1px', marginRight: 2 }} />
            {t('setup.open')}
          </button>
        )}
      </p>
    </div>
  );
}
