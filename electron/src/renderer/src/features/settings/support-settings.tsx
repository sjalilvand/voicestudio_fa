import { runRendererTask } from '@/lib/global-error-recovery';
import {
  ArrowUpRightIcon,
  CheckIcon,
  CoffeeIcon,
  CreditCardIcon,
  GemIcon,
  Globe2Icon,
  LightbulbIcon,
  MailIcon,
  MessagesSquareIcon,
  RadioIcon,
  ShieldCheckIcon,
  StarIcon,
} from 'lucide-react';
import { useSearch, useNavigate } from '@tanstack/react-router';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { brandIcon } from '@/lib/brand';
import { DonationGoal } from './donation-goal';
import { ReportBug } from '@/components/report-bug';
import { ExternalLink } from '@/components/external-link';
import { KOFI_URL, PAYPAL_URL } from '../../../../../../frontend/src/utils/donateLinks';
import {
  SPONSORS,
  SPONSOR_TIERS,
  SPONSOR_CONTACT,
} from '../../../../../../frontend/src/config/sponsors';
import {
  ISSUES_URL,
  DISCORD_URL,
  SECURITY_URL,
  EMAIL,
  WEBSITE_URL,
  X_URL,
} from '../../../../../../frontend/src/utils/contactLinks';
import './support-settings.css';

export function SupportSettings() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as { compare?: boolean };
  const comparison = useRef<HTMLElement>(null);
  useEffect(() => {
    if (search.compare) {
      comparison.current?.scrollIntoView({ block: 'start' });
      comparison.current?.focus({ preventScroll: true });
    }
  }, [search.compare]);
  const [amount, setAmount] = useState<number | 'custom' | null>(null);
  const sponsorGroups = [...SPONSOR_TIERS, '']
    .map((tier) => ({
      tier,
      sponsors: SPONSORS.filter((sponsor) =>
        tier ? sponsor.tier === tier : !SPONSOR_TIERS.includes(sponsor.tier),
      ),
    }))
    .filter((group) => group.sponsors.length);
  const channels = [
    ['contact.feature_cta', ISSUES_URL, LightbulbIcon],
    ['contact.community_cta', DISCORD_URL, MessagesSquareIcon],
    ['contact.follow_cta', X_URL, RadioIcon],
    ['contact.security_cta', SECURITY_URL, ShieldCheckIcon],
    ['contact.email', 'mailto:' + EMAIL, MailIcon],
    ['contact.website', WEBSITE_URL, Globe2Icon],
  ] as const;

  return (
    <div className="support-studio">
      <header className="support-intro">
        <div className="support-emblem" aria-hidden="true">
          <img src={brandIcon} alt="" width={100} height={100} />
        </div>
        <h1>{t('donate.hero_title')}</h1>
        <p>{t('donate.footer')}</p>
      </header>

      {search.compare && (
        <section
          ref={comparison}
          tabIndex={-1}
          aria-labelledby="support-plans-title"
          className="mb-6 scroll-mt-6 rounded-2xl border border-primary/25 bg-card p-6 outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <h2 id="support-plans-title" className="text-xl font-semibold tracking-tight">
            {t('supportPlans.title')}
          </h2>
          <table className="mt-5 w-full text-left text-sm">
            <thead>
              <tr>
                <th scope="col" className="pb-3">
                  {t('supportPlans.sponsor_bar')}
                </th>
                <th scope="col" className="pb-3">
                  {t('supportPlans.free')}
                </th>
                <th scope="col" className="pb-3 text-primary">
                  {t('supportPlans.pro')}
                </th>
              </tr>
            </thead>
            <tbody>
              {[
                ['sponsor_bar', 'visible', 'hideable'],
                ['telemetry', 'opt_in', 'disabled'],
                ['badge', 'standard', 'included'],
                ['advanced', 'standard', 'included'],
              ].map(([label, free, pro]) => (
                <tr key={label} className="border-t border-border">
                  <th scope="row" className="py-4 font-normal">
                    {t('supportPlans.' + label)}
                  </th>
                  <td className="p-2 text-muted-foreground">{t('supportPlans.' + free)}</td>
                  <td className="p-2">{t('supportPlans.' + pro)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-muted-foreground">{t('supportPlans.unavailable')}</p>
        </section>
      )}

      <section className="support-giving" aria-label={t('donate.goal.title')}>
        <div className="support-progress">
          <DonationGoal />
        </div>
        <div className="support-checkout">
          <h2>{t('donate.suggested_title')}</h2>
          <div className="support-amounts" role="group" aria-label={t('donate.suggested_title')}>
            {[10, 20, 50, 'custom' as const].map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={amount === value}
                onClick={() => setAmount(amount === value ? null : value)}
              >
                <CheckIcon aria-hidden="true" className="support-selected" />
                <span>{value === 'custom' ? t('donate.custom') : '$' + value}</span>
              </button>
            ))}
          </div>
          <div className="support-payments" role="group" aria-label={t('donate.choose_method')}>
            <ExternalLink href={KOFI_URL}>
              <CoffeeIcon aria-hidden="true" />
              Ko-fi
            </ExternalLink>
            <ExternalLink
              href={typeof amount === 'number' ? PAYPAL_URL + '/' + amount : PAYPAL_URL}
            >
              <CreditCardIcon aria-hidden="true" />
              PayPal
            </ExternalLink>
          </div>
          <p className="support-payment-note">
            {typeof amount === 'number'
              ? t('donate.choose_method_amount', { amount })
              : t('donate.choose_method')}
          </p>
        </div>
      </section>

      <div className="support-community" role="group" aria-label={t('support.other_ways')}>
        <span>{t('support.other_ways')}</span>
        <ExternalLink href="https://github.com/debpalash/VoiceStudio">
          <StarIcon aria-hidden="true" />
          {t('support.star_github')}
        </ExternalLink>
        <ExternalLink href={DISCORD_URL}>
          <MessagesSquareIcon aria-hidden="true" />
          {t('support.join_discord')}
        </ExternalLink>
      </div>

      <div className="support-opportunities">
        <section
          className="support-tile support-sponsors"
          aria-labelledby="support-sponsors-heading"
        >
          <GemIcon className="support-tile-icon" aria-hidden="true" />
          <h2 id="support-sponsors-heading">{t('support.sponsors_title')}</h2>
          <p>{t(SPONSORS.length ? 'support.sponsors_lead' : 'support.sponsors_empty_title')}</p>
          {SPONSORS.length === 0 && (
            <div className="support-logo-slot" aria-hidden="true">
              <GemIcon />
              <span>{t('support.sponsors_empty_desc')}</span>
              <span className="support-logo-plus">+</span>
            </div>
          )}
          {sponsorGroups.map(({ tier, sponsors }) => (
            <div key={tier} className="support-sponsor-group">
              {tier && <h3>{t('support.sponsors_tier_' + tier)}</h3>}
              <div>
                {sponsors.map((sponsor) => (
                  <ExternalLink key={sponsor.url} href={sponsor.url}>
                    <img src={sponsor.logoUrl} alt="" loading="lazy" />
                    {sponsor.name}
                  </ExternalLink>
                ))}
              </div>
            </div>
          ))}
          <div className="support-tile-actions">
            <ExternalLink href={SPONSOR_CONTACT.githubIssue}>
              {t('support.sponsors_become')}
            </ExternalLink>
            <ExternalLink href={SPONSOR_CONTACT.docsUrl}>
              {t('support.sponsors_learn_more')}
            </ExternalLink>
          </div>
        </section>
        <section className="support-tile support-license" aria-labelledby="support-pro-heading">
          <span className="mb-4 w-fit rounded-md bg-primary/10 px-2 py-1 text-xs font-semibold tracking-wider text-primary">
            {t('supportPlans.pro')}
          </span>
          <h2 id="support-pro-heading">{t('supportPlans.pro')}</h2>
          <ul className="my-4 grid gap-3 text-sm text-muted-foreground">
            {[
              ['telemetry', 'disabled'],
              ['sponsor_bar', 'hideable'],
              ['badge', 'included'],
              ['advanced', 'included'],
            ].map(([label, value]) => (
              <li key={label} className="flex items-center gap-2">
                <CheckIcon aria-hidden="true" className="size-4 shrink-0 text-primary" />
                <span>
                  {t('supportPlans.' + label)} · {t('supportPlans.' + value)}
                </span>
              </li>
            ))}
          </ul>
          <p>{t('supportPlans.unavailable')}</p>
          <button
            type="button"
            onClick={() => runRendererTask('Open support', () => navigate({ to: '/settings/support', search: { compare: true } }))}
            className="mt-4 flex min-h-11 items-center gap-2 text-sm font-medium text-primary hover:underline focus-visible:outline-2 focus-visible:outline-primary"
          >
            {t('supportPlans.title')}
            <ArrowUpRightIcon aria-hidden="true" className="size-3" />
          </button>
        </section>
      </div>

      <section className="support-contact" aria-labelledby="support-contact-heading">
        <div className="support-contact-heading">
          <h2 id="support-contact-heading">{t('contact.channels_label')}</h2>
          <ReportBug />
        </div>
        <div className="support-channel-grid">
          {channels.map(([label, href, Icon]) => (
            <ExternalLink key={href} href={href}>
              <Icon aria-hidden="true" />
              <span>{t(label)}</span>
            </ExternalLink>
          ))}
        </div>
      </section>
    </div>
  );
}
