import React from 'react';
import { useTranslation } from 'react-i18next';
import { Heart, ExternalLink, ArrowLeft, Building2 } from 'lucide-react';
import { Button } from '../ui';
import { openExternal } from '../api/external';
import './DonatePage.css';

const METHODS = [
  {
    id: 'github',
    label: 'GitHub Sponsors',
    descriptionKey: 'donate.github_desc',
    url: 'https://github.com/debpalash',
    icon: '🐙',
  },
  {
    id: 'kofi',
    label: 'Ko-fi',
    descriptionKey: 'donate.coffee_desc',
    url: 'https://ko-fi.com/debpalash',
    icon: '☕',
  },
  {
    id: 'paypal',
    label: 'PayPal',
    descriptionKey: 'donate.paypal_desc',
    url: 'https://paypal.me/palashCoder',
    icon: '💳',
  },
];

function LinkCard({ method, style }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className="donate-card donate-card--link lp-glow-card"
      style={style}
      onClick={() => openExternal(method.url)}
    >
      <span className="donate-card__glow" aria-hidden="true" />
      <div className="donate-card__icon">{method.icon}</div>
      <div className="donate-card__body">
        <div className="donate-card__label">{method.label}</div>
        <div className="donate-card__desc">{t(method.descriptionKey)}</div>
      </div>
      <div className="donate-card__arrow">
        <ExternalLink size={14} />
      </div>
    </button>
  );
}

export default function DonatePage({ onBack, onEnterprise }) {
  const { t } = useTranslation();
  return (
    <div className="donate-page">
      {/* Aurora backdrop — same as Launchpad */}
      <div className="lp-aurora" aria-hidden="true">
        <span className="lp-aurora__blob lp-aurora__blob--pink" />
        <span className="lp-aurora__blob lp-aurora__blob--green" />
        <span className="lp-aurora__blob lp-aurora__blob--amber" />
      </div>

      {/* Top bar: Back (left) + Commercial License (right) */}
      <div className="donate-page__topbar">
        <Button
          variant="subtle"
          size="sm"
          onClick={onBack}
          leading={<ArrowLeft size={14} />}
        >
          {t('donate.back')}
        </Button>
        {onEnterprise && (
          <Button
            variant="subtle"
            size="sm"
            onClick={onEnterprise}
            leading={<Building2 size={14} />}
            trailing={<ExternalLink size={12} />}
          >
            {t('donate.commercial')}
          </Button>
        )}
      </div>

      <div className="donate-page__content">
        {/* Hero */}
        <div className="donate-hero">
          <div className="donate-hero__icon-wrap">
            <Heart size={24} className="donate-hero__heart" />
          </div>
          <h2 className="donate-hero__title">
            {t('donate.hero_title')}
            <span className="lp-hero__sweep" aria-hidden="true" />
          </h2>
          <p className="donate-hero__subtitle">
            {t('donate.hero_desc')}
          </p>
        </div>

        {/* Platforms */}
        <section className="donate-section">
          <div className="donate-section__title">
            <span>{t('donate.platforms')}</span>
          </div>
          <div className="donate-grid donate-grid--links">
            {METHODS.map((m, i) => (
              <LinkCard
                key={m.id}
                method={m}
                style={{ '--anim-i': i, '--card-hue': '#d3869b' }}
              />
            ))}
          </div>
        </section>

        <div className="donate-footer">
          {t('donate.footer')}
        </div>
      </div>
    </div>
  );
}
