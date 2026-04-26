import React from 'react';
import {
  ArrowLeft, Shield, Zap, Users, Headphones, Code, Globe,
  BarChart3, Building2, Mail, ExternalLink, Check,
} from 'lucide-react';
import { Button } from '../ui';
import { openExternal } from '../api/external';
import './EnterprisePage.css';

const TIERS = [
  {
    id: 'startup',
    name: 'Startup',
    price: '$249',
    period: '/year',
    accent: '#8ec07c',
    best: false,
    description: 'For small teams shipping content with AI voices.',
    perks: [
      'Commercial use license for up to 5 seats',
      'Remove invisible watermark from exports',
      'Priority bug fixes via email',
      'Invoice + receipt for accounting',
    ],
  },
  {
    id: 'business',
    name: 'Business',
    price: '$999',
    period: '/year',
    accent: '#d3869b',
    best: true,
    description: 'For production teams that need reliability and support.',
    perks: [
      'Everything in Startup',
      'Unlimited seats within one organization',
      'Dedicated Slack/Discord channel with core team',
      '48-hour response SLA on critical issues',
      'Custom model fine-tuning guidance',
      'Early access to beta features & engines',
      'Logo on README + website acknowledgments',
    ],
  },
  {
    id: 'enterprise',
    name: 'Enterprise',
    price: 'Custom',
    period: '',
    accent: '#fe8019',
    best: false,
    description: 'On-prem deployment, SLA, and dedicated engineering.',
    perks: [
      'Everything in Business',
      'On-premise deployment support',
      'Custom SLA (up to 4-hour response)',
      'Dedicated integration engineer',
      'Private model hosting & training',
      'Custom API/SDK development',
      'Source code escrow',
      'Multi-year volume discounts',
    ],
  },
];

const WHY_ITEMS = [
  { icon: Shield, label: 'Full IP ownership', desc: 'Your voices, your data, your servers. No third-party dependency.' },
  { icon: Zap, label: 'Zero per-minute costs', desc: 'One flat annual fee. Generate millions of minutes without usage caps.' },
  { icon: Users, label: 'Team-wide access', desc: 'Share across your org. No per-seat API key management.' },
  { icon: Headphones, label: 'Direct support', desc: 'Talk to the engineers who built it, not a helpdesk.' },
  { icon: Code, label: 'Open source core', desc: 'Audit the code. Fork if needed. No vendor lock-in, ever.' },
  { icon: Globe, label: '646 languages', desc: 'Ship global content from one tool. No third-party locale add-ons.' },
];

function TierCard({ tier }) {
  return (
    <div
      className={`ent-tier ${tier.best ? 'ent-tier--best' : ''}`}
      style={{ '--tier-accent': tier.accent }}
    >
      {tier.best && <span className="ent-tier__badge">Most popular</span>}
      <div className="ent-tier__icon-wrap">
        <Building2 size={18} />
      </div>
      <h3 className="ent-tier__name">{tier.name}</h3>
      <div className="ent-tier__price">
        <span className="ent-tier__amount">{tier.price}</span>
        {tier.period && <span className="ent-tier__period">{tier.period}</span>}
      </div>
      <p className="ent-tier__desc">{tier.description}</p>
      <ul className="ent-tier__perks">
        {tier.perks.map((p, i) => (
          <li key={i}>
            <Check size={12} className="ent-tier__check" />
            {p}
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="ent-tier__cta"
        onClick={() => openExternal(`mailto:OmniVoice@palash.dev?subject=OmniVoice ${tier.name} License&body=Hi Palash,%0A%0AI'm interested in the ${tier.name} license for OmniVoice Studio.%0A%0AOrganization:%0ATeam size:%0AUse case:%0A`)}
      >
        <Mail size={13} />
        {tier.price === 'Custom' ? 'Contact Sales' : 'Get Started'}
      </button>
    </div>
  );
}

export default function EnterprisePage({ onBack }) {
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
          Back to Studio
        </Button>
      </div>

      <div className="enterprise-page__content">
        {/* Hero */}
        <div className="ent-hero">
          <span className="ent-hero__kicker">Commercial License</span>
          <h2 className="ent-hero__title">
            Ship AI voices in production
            <span className="lp-hero__sweep" aria-hidden="true" />
          </h2>
          <p className="ent-hero__subtitle">
            OmniVoice Studio is free for personal and non-commercial use.
            For commercial products, SaaS, and enterprise — grab a license
            that fits your team. <strong>30-day free evaluation included.</strong>
          </p>
        </div>

        {/* Why Businesses Choose OmniVoice */}
        <section className="ent-why">
          <div className="ent-section-title">
            <span>Why businesses choose OmniVoice</span>
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

        {/* Pricing Tiers */}
        <section className="ent-tiers-section">
          <div className="ent-section-title">
            <span>Plans</span>
          </div>
          <div className="ent-tiers">
            {TIERS.map(t => <TierCard key={t.id} tier={t} />)}
          </div>
        </section>

        {/* FAQ */}
        <section className="ent-faq">
          <div className="ent-section-title">
            <span>Common questions</span>
          </div>
          <div className="ent-faq__list">
            <details className="ent-faq__item">
              <summary>Do I need a license for internal tools?</summary>
              <p>If the tool generates revenue or is used in a commercial product — yes. Internal R&D and prototyping during the 30-day evaluation period is free.</p>
            </details>
            <details className="ent-faq__item">
              <summary>Can I try before I buy?</summary>
              <p>Absolutely. Every plan includes a 30-day free evaluation. No credit card required — just email us and we'll activate it.</p>
            </details>
            <details className="ent-faq__item">
              <summary>What about the watermark?</summary>
              <p>The invisible AudioSeal watermark is embedded by default. Commercial licensees can disable it in Settings → Privacy. Free/personal use always includes the watermark.</p>
            </details>
            <details className="ent-faq__item">
              <summary>Do you offer multi-year discounts?</summary>
              <p>Yes — Enterprise tier includes volume and multi-year pricing. Contact us for a custom quote.</p>
            </details>
          </div>
        </section>

        {/* CTA footer */}
        <div className="ent-cta-footer">
          <p>Questions? Reach out at <button type="button" className="ent-cta-footer__link" onClick={() => openExternal('mailto:OmniVoice@palash.dev')}>OmniVoice@palash.dev</button></p>
          <p className="ent-cta-footer__sub">
            Join our <button type="button" className="ent-cta-footer__link" onClick={() => openExternal('https://discord.gg/aRRdVj3de7')}>Discord</button> for community support.
          </p>
        </div>
      </div>
    </div>
  );
}
