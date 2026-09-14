import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  BUNDLED_PROGRESS,
  loadDonationProgress,
  progressPct,
  isGoalMet,
  formatMoney,
} from '../../../../../../frontend/src/api/donation';
import snapshotUrl from '../../../../../../frontend/public/donation_progress.json?url';

export function DonationGoal() {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ['donation-progress'],
    initialData: BUNDLED_PROGRESS,
    initialDataUpdatedAt: 0,
    queryFn: ({ signal }) =>
      loadDonationProgress((_url, options) => fetch(snapshotUrl, { ...options, signal })),
    staleTime: 60_000,
  });
  const pct = Math.round(progressPct(data) * 100);
  const raised = formatMoney(data.raised, data.currency);
  const goal = formatMoney(data.goal, data.currency);
  return (
    <div className="space-y-2 rounded-lg bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span>{t('donate.goal.title')}</span>
        <span className="tabular-nums">{pct}%</span>
      </div>
      <div
        role="progressbar"
        aria-label={t('donate.goal.aria', { raised, goal })}
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1.5 overflow-hidden rounded-full bg-muted"
      >
        <div className="h-full rounded-full bg-primary" style={{ width: pct + '%' }} />
      </div>
      <p className="text-xs text-muted-foreground">
        {isGoalMet(data) ? (
          t('donate.goal.met', { raised })
        ) : (
          <>
            {raised} {t('donate.goal.of')} {goal} {t('donate.goal.per_month')}
          </>
        )}
      </p>
      {!isGoalMet(data) && (
        <p className="text-xs text-muted-foreground">
          {t('donate.goal.remaining', {
            amount: formatMoney(Math.max(0, data.goal - data.raised), data.currency),
          })}
        </p>
      )}
      {data.sponsorCount > 0 && (
        <p className="text-xs text-muted-foreground">
          {t('donate.goal.social_proof', { count: data.sponsorCount })}
        </p>
      )}
    </div>
  );
}
