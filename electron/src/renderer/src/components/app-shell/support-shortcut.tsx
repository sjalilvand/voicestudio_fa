import { Link } from '@tanstack/react-router';
import { ArrowUpRightIcon, GemIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';

export function SupportShortcut() {
  const { t } = useTranslation();
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Link
            to="/settings/support"
            aria-label={t('supportPlans.title')}
            className="app-no-drag flex h-8 items-center gap-1.5 rounded-lg border border-primary/25 bg-primary/10 px-2.5 text-primary hover:border-primary/45 hover:bg-primary/15 focus-visible:outline-2 focus-visible:outline-primary motion-safe:transition-colors"
          />
        }
      >
        <GemIcon aria-hidden="true" className="size-3.5" />
        <span className="hidden text-xs font-semibold sm:inline">{t('supportPlans.pro')}</span>
        <ArrowUpRightIcon aria-hidden="true" className="size-3" />
      </TooltipTrigger>
      <TooltipContent surface="theme" side="bottom">
        {t('supportPlans.title')}
      </TooltipContent>
    </Tooltip>
  );
}
