import { Link } from '@tanstack/react-router';
import { ArrowUpRightIcon, GemIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import './support-shortcut.css';

export function SupportShortcut() {
  const { t } = useTranslation();
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Link
            to="/pro"
            aria-label={t('supportPlans.get_pro')}
            className="support-shortcut app-no-drag flex h-8 items-center gap-1.5 px-1.5 text-primary hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary motion-safe:transition-colors"
          />
        }
      >
        <GemIcon aria-hidden="true" className="size-3.5" />
        <span className="hidden text-xs font-semibold sm:inline">{t('supportPlans.get_pro')}</span>
        <ArrowUpRightIcon aria-hidden="true" className="size-3" />
      </TooltipTrigger>
      <TooltipContent surface="theme" side="bottom">
        {t('supportPlans.get_pro')}
      </TooltipContent>
    </Tooltip>
  );
}
