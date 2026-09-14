import {
  BadgeCheckIcon,
  BugIcon,
  Building2Icon,
  CoffeeIcon,
  CreditCardIcon,
  Globe2Icon,
  HeartHandshakeIcon,
  LightbulbIcon,
  MailIcon,
  MessagesSquareIcon,
  RadioIcon,
  ShieldAlertIcon,
  SparklesIcon,
  UsersRoundIcon,
} from 'lucide-react';
import { useState } from 'react';
import { DonationGoal } from './donation-goal';
import { ReportBug } from '@/components/report-bug';
import { useTranslation } from 'react-i18next';
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
  LICENSE_MAILTO,
} from '../../../../../../frontend/src/utils/contactLinks';
import { Button } from '@/components/ui/button';
import { SettingsSection } from './settings-layout';

export function SupportSettings() {
  const { t } = useTranslation();
  const [amount, setAmount] = useState<number | null>(null);
  const sponsorGroups = [...SPONSOR_TIERS, '']
    .map((tier) => ({
      tier,
      sponsors: SPONSORS.filter((sponsor) =>
        tier ? sponsor.tier === tier : !SPONSOR_TIERS.includes(sponsor.tier),
      ),
    }))
    .filter((group) => group.sponsors.length);
  const enterpriseBenefits = [
    ['benefit_ip', ShieldAlertIcon],
    ['benefit_cost', BadgeCheckIcon],
    ['benefit_support', HeartHandshakeIcon],
  ] as const;
  const contactChannels = [
    ['contact.feature_title', 'contact.feature_cta', ISSUES_URL, LightbulbIcon],
    ['contact.community_title', 'contact.community_cta', DISCORD_URL, MessagesSquareIcon],
    ['contact.follow_title', 'contact.follow_cta', X_URL, RadioIcon],
    ['contact.security_title', 'contact.security_cta', SECURITY_URL, ShieldAlertIcon],
    ['contact.email_desc', 'contact.email', 'mailto:' + EMAIL, MailIcon],
    ['contact.website_desc', 'contact.website', WEBSITE_URL, Globe2Icon],
  ] as const;
  return (
    <>
      <SettingsSection icon={HeartHandshakeIcon} title={t('donate.hero_title')}>
        <div className="relative isolate space-y-5 overflow-hidden p-5 @xl:p-6">
          <div className="pointer-events-none absolute -top-24 right-0 -z-10 size-64 rounded-full bg-primary/15 blur-3xl" />
          <div className="flex items-start gap-4">
            <span className="grid size-11 shrink-0 place-items-center rounded-2xl border border-primary/25 bg-primary/12 text-primary shadow-[inset_0_1px_0_rgb(255_255_255/12%),0_12px_30px_-18px_var(--primary)]">
              <SparklesIcon className="size-5" />
            </span>
            <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
              {t('donate.hero_desc')}
            </p>
          </div>
          <DonationGoal />
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label={t('donate.suggested_title')}
          >
            {[10, 20, 50, null].map((value) => (
              <Button
                key={String(value)}
                size="sm"
                variant={amount === value ? 'default' : 'outline'}
                className="min-w-16 rounded-full"
                aria-pressed={amount === value}
                onClick={() => setAmount(value)}
              >
                {value === null ? t('donate.custom') : '$' + value}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label={t('donate.choose_method')}>
            <ExternalLink href={KOFI_URL}>
              <CoffeeIcon />
              Ko-fi
            </ExternalLink>
            <ExternalLink href={amount === null ? PAYPAL_URL : PAYPAL_URL + '/' + amount}>
              <CreditCardIcon />
              PayPal
            </ExternalLink>
          </div>
        </div>
      </SettingsSection>
      <SettingsSection icon={UsersRoundIcon} title={t('support.sponsors_title')}>
        <div className="space-y-4 p-4">
          {SPONSORS.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('support.sponsors_empty_title')}</p>
          )}
          {sponsorGroups.map(({ tier, sponsors }) => (
            <div key={tier} className="space-y-2">
              {tier && (
                <h3 className="text-sm font-medium">{t('support.sponsors_tier_' + tier)}</h3>
              )}
              <div className="flex flex-wrap gap-2">
                {sponsors.map((sponsor) => (
                  <ExternalLink key={sponsor.url} href={sponsor.url}>
                    <img
                      src={sponsor.logoUrl}
                      alt=""
                      loading="lazy"
                      className="max-h-6 max-w-24 object-contain"
                    />
                    {sponsor.name}
                  </ExternalLink>
                ))}
              </div>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <ExternalLink href={SPONSOR_CONTACT.githubIssue}>
              <HeartHandshakeIcon />
              {t('support.sponsors_become')}
            </ExternalLink>
            <ExternalLink href={SPONSOR_CONTACT.docsUrl}>
              <Globe2Icon />
              {t('support.sponsors_learn_more')}
            </ExternalLink>
          </div>
        </div>
      </SettingsSection>
      <SettingsSection icon={Building2Icon} title={t('enterprise.title')}>
        <div className="space-y-4 p-4">
          <p className="text-sm leading-relaxed text-muted-foreground">
            {t('enterprise.hero_simple')}
          </p>
          <ul className="space-y-1 text-sm">
            {enterpriseBenefits.map(([key, Icon]) => (
              <li key={key} className="flex items-start gap-2.5 rounded-lg bg-muted/25 px-3 py-2">
                <Icon className="mt-0.5 size-4 shrink-0 text-primary" />
                <span>{t('enterprise.' + key)}</span>
              </li>
            ))}
          </ul>
          <ExternalLink href={LICENSE_MAILTO}>
            <MailIcon />
            {t('enterprise.request_quote')}
          </ExternalLink>
        </div>
      </SettingsSection>
      <SettingsSection icon={MessagesSquareIcon} title={t('contact.channels_label')}>
        <div className="flex flex-wrap items-center justify-between gap-3 p-4">
          <p className="flex items-center gap-2.5 text-sm">
            <BugIcon className="size-4 text-muted-foreground" />
            {t('contact.bug_title')}
          </p>
          <ReportBug />
        </div>
        {contactChannels.map(([title, label, href, Icon]) => (
          <div key={href} className="flex flex-wrap items-center justify-between gap-3 p-4">
            <p className="flex items-center gap-2.5 text-sm">
              <Icon className="size-4 shrink-0 text-muted-foreground" />
              {t(title)}
            </p>
            <ExternalLink href={href}>{t(label)}</ExternalLink>
          </div>
        ))}
      </SettingsSection>
    </>
  );
}
