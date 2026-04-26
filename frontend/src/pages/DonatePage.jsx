import React, { useState } from 'react';
import { Heart, Copy, ExternalLink, ArrowLeft, Check, Building2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { QRCodeSVG } from 'qrcode.react';
import { Button } from '../ui';
import { openExternal } from '../api/external';
import './DonatePage.css';

const METHODS = [
  {
    id: 'github',
    label: 'GitHub Sponsors',
    description: 'Recurring or one-time — directly through GitHub.',
    url: 'https://github.com/debpalash',
    icon: '🐙',
    type: 'link',
  },
  {
    id: 'patreon',
    label: 'Patreon',
    description: 'Monthly support with early access perks.',
    url: 'https://patreon.com/omnivoicestudio',
    icon: '🎨',
    type: 'link',
  },
  {
    id: 'kofi',
    label: 'Ko-fi',
    description: 'Buy the team a coffee. No account needed.',
    url: 'https://ko-fi.com/debpalash',
    icon: '☕',
    type: 'link',
  },
  {
    id: 'paypal',
    label: 'PayPal',
    description: 'Quick one-time or recurring via PayPal.',
    url: 'https://paypal.me/palashCoder',
    icon: '💳',
    type: 'link',
  },
  {
    id: 'btc',
    label: 'Bitcoin',
    description: 'Native BTC — any amount.',
    address: 'bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh',
    icon: '₿',
    type: 'crypto',
    network: 'Bitcoin (BTC)',
    protocol: 'bitcoin',
  },
  {
    id: 'eth',
    label: 'Ethereum',
    description: 'ETH or ERC-20 tokens.',
    address: '0x71C7656EC7ab88b098defB751B7401B5f6d8976F',
    icon: 'Ξ',
    type: 'crypto',
    network: 'Ethereum (ETH / ERC-20)',
    protocol: 'ethereum',
  },
  {
    id: 'sol',
    label: 'Solana',
    description: 'SOL or SPL tokens.',
    address: '7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV',
    icon: '◎',
    type: 'crypto',
    network: 'Solana (SOL)',
    protocol: 'solana',
  },
];

function CryptoCard({ method, style }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(method.address);
      setCopied(true);
      toast.success(`${method.label} address copied`);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error('Copy failed');
    }
  };
  return (
    <div className="donate-card lp-glow-card" style={style}>
      <span className="donate-card__glow" aria-hidden="true" />
      <div className="donate-card__icon">{method.icon}</div>
      <div className="donate-card__body">
        <div className="donate-card__label">{method.label}</div>
        <div className="donate-card__desc">{method.description}</div>
        <div className="donate-card__addr-row">
          <code className="donate-card__addr">{method.address}</code>
          <div className="donate-card__addr-actions">
            <button className="donate-card__addr-btn" onClick={handleCopy} title="Copy address">
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </button>
            {method.protocol && (
              <button
                className="donate-card__addr-btn donate-card__addr-btn--open"
                onClick={() => openExternal(`${method.protocol}:${method.address}`)}
                title="Open in desktop wallet"
              >
                <ExternalLink size={11} />
                <span className="donate-card__open-label">Open</span>
              </button>
            )}
          </div>
        </div>
        <span className="donate-card__network">{method.network}</span>
      </div>
      <div className="donate-card__qr">
        <QRCodeSVG
          value={`${method.protocol || ''}:${method.address}`}
          size={48}
          bgColor="#ffffff"
          fgColor="#000000"
          level="M"
          includeMargin={false}
        />
      </div>
    </div>
  );
}

function LinkCard({ method, style }) {
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
        <div className="donate-card__desc">{method.description}</div>
      </div>
      <div className="donate-card__arrow">
        <ExternalLink size={14} />
      </div>
    </button>
  );
}

export default function DonatePage({ onBack, onEnterprise }) {
  const links = METHODS.filter(m => m.type === 'link');
  const crypto = METHODS.filter(m => m.type === 'crypto');

  return (
    <div className="donate-page">
      {/* Aurora backdrop — same as Launchpad */}
      <div className="lp-aurora" aria-hidden="true">
        <span className="lp-aurora__blob lp-aurora__blob--pink" />
        <span className="lp-aurora__blob lp-aurora__blob--green" />
        <span className="lp-aurora__blob lp-aurora__blob--amber" />
      </div>

      {/* Back button */}
      <div className="donate-page__back">
        <Button
          variant="subtle"
          size="sm"
          onClick={onBack}
          leading={<ArrowLeft size={14} />}
        >
          Back to Studio
        </Button>
      </div>

      <div className="donate-page__content">
        {/* Hero */}
        <div className="donate-hero">
          <div className="donate-hero__icon-wrap">
            <Heart size={24} className="donate-hero__heart" />
          </div>
          <h2 className="donate-hero__title">
            Support OmniVoice
            <span className="lp-hero__sweep" aria-hidden="true" />
          </h2>
          <p className="donate-hero__subtitle">
            OmniVoice is free, open-source, and runs entirely on your hardware.
            If it brings value to your workflow, consider supporting the core team.
          </p>
        </div>

        {/* Platforms */}
        <section className="donate-section">
          <div className="donate-section__title">
            <span>Platforms</span>
          </div>
          <div className="donate-grid donate-grid--links">
            {links.map((m, i) => (
              <LinkCard
                key={m.id}
                method={m}
                style={{ '--anim-i': i, '--card-hue': '#d3869b' }}
              />
            ))}
          </div>
        </section>

        {/* Cryptocurrency */}
        <section className="donate-section">
          <div className="donate-section__title">
            <span>Cryptocurrency</span>
          </div>
          <div className="donate-grid donate-grid--crypto">
            {crypto.map((m, i) => (
              <CryptoCard
                key={m.id}
                method={m}
                style={{ '--anim-i': i + 3, '--card-hue': '#fe8019' }}
              />
            ))}
          </div>
        </section>

        <div className="donate-footer">
          Every contribution helps push the boundaries of local AI. ♥
        </div>

        {/* Enterprise CTA */}
        {onEnterprise && (
          <div className="donate-enterprise-cta">
            <button type="button" className="donate-card donate-card--link" onClick={onEnterprise} style={{ '--card-hue': '#fe8019' }}>
              <span className="donate-card__glow" aria-hidden="true" />
              <div className="donate-card__icon"><Building2 size={16} /></div>
              <div className="donate-card__body">
                <div className="donate-card__label">Commercial License</div>
                <div className="donate-card__desc">Using OmniVoice in a product or business? See enterprise plans.</div>
              </div>
              <div className="donate-card__arrow"><ExternalLink size={14} /></div>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
