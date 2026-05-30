import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft, Shield, Zap, Users, Headphones, Code, Globe,
  Building2, Mail,
} from 'lucide-react';
import { Button } from '../ui';
import { openExternal } from '../api/external';
import './EnterprisePage.css';

export default function EnterprisePage({ onBack }) {
  const { t } = useTranslation();

  const WHY_ITEMS = [
    { icon: Shield, label: t('enterprise.benefit_ip'), desc: t('enterprise.benefit_ip_desc') },
    { icon: Zap, label: t('enterprise.benefit_cost'), desc: t('enterprise.benefit_cost_desc') },
    { icon: Users, label: t('enterprise.benefit_team'), desc: t('enterprise.benefit_team_desc') },
    { icon: Headphones, label: t('enterprise.benefit_support'), desc: t('enterprise.benefit_support_desc') },
    { icon: Code, label: t('enterprise.benefit_source'), desc: t('enterprise.benefit_source_desc') },
    { icon: Globe, label: t('enterprise.benefit_lang'), desc: t('enterprise.benefit_lang_desc') },
  ];

  return (
    <div className="enterprise-page">
      {/* Aurora backdrop — same as Launchpad */}
      <div className="lp-aurora" aria-hidden="true">
        <span className="lp-aurora__blob lp-aurora__blob--pink" />
        <span className="lp-aurora__blob lp-aurora__blob--green" />
        <span className="lp-aurora__blob lp-aurora__blob--amber" />
      </div>

      <div className="enterprise-page__back">
        <Button
          variant="subtle"
          size="sm"
          onClick={onBack}
          leading={<ArrowLeft size={14} />}
        >
          {t('enterprise.back')}
        </Button>
      </div>

      <div className="enterprise-page__content">
        {/* Hero */}
        <div className="ent-hero">
          <span className="ent-hero__kicker">{t('enterprise.badge')}</span>
          <h2 className="ent-hero__title">
            {t('enterprise.hero_title')}
            <span className="lp-hero__sweep" aria-hidden="true" />
          </h2>
          <p className="ent-hero__subtitle">
            {t('enterprise.hero_desc')}
          </p>
          <p className="ent-hero__subtitle">
            {t('enterprise.hero_note')}
          </p>
        </div>

        {/* Why Businesses Choose OmniVoice */}
        <section className="ent-why">
          <div className="ent-section-title">
            <span>{t('enterprise.why_title')}</span>
          </div>
          <div className="ent-why__grid">
            {WHY_ITEMS.map(({ icon: Icon, label, desc }) => (
              <div key={label} className="ent-why__card">
                <div className="ent-why__icon"><Icon size={16} /></div>
                <div className="ent-why__label">{label}</div>
                <div className="ent-why__desc">{desc}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Pricing — coming soon */}
        <section className="ent-tiers-section">
          <div className="ent-section-title">
            <span>{t('enterprise.pricing_title')}</span>
          </div>
          <div className="ent-coming-soon">
            <p>
              <strong>{t('enterprise.pricing_desc')}</strong>{' '}
              {t('enterprise.pricing_detail')}
            </p>
            <button
              type="button"
              className="ent-coming-soon__cta"
              onClick={() => openExternal('mailto:OmniVoice@palash.dev?subject=OmniVoice Commercial License Inquiry&body=Hi Palash,%0A%0AI%27d like to talk about a commercial license for OmniVoice Studio.%0A%0AOrganization:%0ATeam size:%0AUse case:%0A')}
            >
              <Mail size={13} />
              {t('enterprise.request_quote')}
            </button>
          </div>
        </section>

        {/* FAQ */}
        <section className="ent-faq">
          <div className="ent-section-title">
            <span>{t('enterprise.faq_title')}</span>
          </div>
          <div className="ent-faq__list">
            <details className="ent-faq__item">
              <summary>Do I need a license for internal tools?</summary>
              <p>Internal use by your employees and contractors is a Permitted Purpose under the FSL — no license required. A commercial license is needed when you make OmniVoice available to others as part of a competing product or service (resale, hosted SaaS, white-label).</p>
            </details>
            <details className="ent-faq__item">
              <summary>Can I try before committing?</summary>
              <p>Yes. The full app is free to download and run locally for evaluation under the FSL. When you're ready to discuss a commercial deployment, email us and we'll work through the details together.</p>
            </details>
            <details className="ent-faq__item">
              <summary>What about the watermark?</summary>
              <p>The invisible AudioSeal watermark is embedded by default. Commercial licensees can disable it in Settings → Privacy. Free/personal use always includes the watermark.</p>
            </details>
            <details className="ent-faq__item">
              <summary>Does the source ever become Apache 2.0?</summary>
              <p>Yes. Each release converts automatically to the Apache License, Version 2.0 on the second anniversary of its publication. That means today's release is Apache 2.0 in two years, no action required from us — the FSL guarantees it irrevocably.</p>
            </details>
          </div>
        </section>

        {/* CTA footer */}
        <div className="ent-cta-footer">
          <p>
            <button
              type="button"
              className="ent-cta-footer__link"
              onClick={() => openExternal('mailto:OmniVoice@palash.dev')}
              title="OmniVoice@palash.dev"
            >
              {t('enterprise.footer_email')}
            </button>
          </p>
          <p className="ent-cta-footer__sub">
            <button
              type="button"
              className="ent-cta-footer__link"
              onClick={() => openExternal('https://discord.gg/bzQavDfVV9')}
              title="discord.gg/bzQavDfVV9"
            >
              {t('enterprise.footer_discord')}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
