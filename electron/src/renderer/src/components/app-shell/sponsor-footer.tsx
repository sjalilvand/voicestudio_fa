import { useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { BlocksIcon, PlusIcon, XIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { runRendererTask } from '@/lib/global-error-recovery';
import { SponsorInquiry } from './sponsor-inquiry';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import './sponsor-footer.css';

// GitHub snapshot checked 2026-09-25. Installer downloads sum .AppImage,
// .deb, .dmg, .exe, .msi and .pkg assets for Electron releases v0.5.3–v0.5.6.
// Views are repository traffic for 2026-09-10 through 2026-09-23.
const SPONSOR_REACH = {
  downloads: '22,678',
  views: '207,236',
  stars: '35,336',
} as const;

/** Lives in the content column, so it never covers the editor or its sidebar. */
export function SponsorFooter() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [inquiryOpen, setInquiryOpen] = useState(false);

  return (
    <div className="sponsor-footer-host">
      <footer aria-label={t('integrationCatalog.title')} className="sponsor-strip">
        <button
          type="button"
          className="sponsor-footer-action"
          onClick={() =>
            runRendererTask('Open integrations', () => navigate({ to: '/integrations' }))
          }
        >
          <BlocksIcon aria-hidden="true" className="size-4" />
          <span>{t('integrationCatalog.title')}</span>
        </button>
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                type="button"
                className="sponsor-footer-action sponsor-footer-action--brand"
                onClick={() => setInquiryOpen(true)}
              />
            }
          >
            <PlusIcon aria-hidden="true" className="size-4" />
            <span>{t('sponsorSlot.footer_brand')}</span>
          </TooltipTrigger>
          <TooltipContent
            surface="theme"
            side="top"
            sideOffset={8}
            className="sponsor-footer-tooltip"
          >
            <strong>{t('sponsorSlot.footer_promo')}</strong>
            <span>{t('sponsorSlot.partner_subtitle')}</span>
            <dl className="sponsor-footer-stats">
              <div>
                <dt>{t('sponsorSlot.footer_downloads')}</dt>
                <dd>{SPONSOR_REACH.downloads}</dd>
              </div>
              <div>
                <dt>{t('sponsorSlot.footer_views')}</dt>
                <dd>{SPONSOR_REACH.views}</dd>
              </div>
              <div>
                <dt>{t('sponsorSlot.footer_stars')}</dt>
                <dd>{SPONSOR_REACH.stars}</dd>
              </div>
            </dl>
            <small>{t('sponsorSlot.footer_stats_note')}</small>
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                type="button"
                className="sponsor-footer-pro"
                aria-label={t('supportPlans.title')}
                onClick={() =>
                  runRendererTask('Open Pro comparison', () =>
                    navigate({ to: '/pro' }),
                  )
                }
              />
            }
          >
            <XIcon aria-hidden="true" className="size-4" />
          </TooltipTrigger>
          <TooltipContent surface="theme" side="top">
            {t('supportPlans.title')}
          </TooltipContent>
        </Tooltip>
        <SponsorInquiry open={inquiryOpen} onOpenChange={setInquiryOpen} />
      </footer>
    </div>
  );
}
