import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { CheckCircleIcon, TriangleAlertIcon, CircleXIcon, ScanSearchIcon } from 'lucide-react';
import type { PreflightReport } from '@shared/api/setup-types';
import { apiJson } from '@/lib/api/client';
import { Button } from '@/components/ui/button';
import { SettingsRow, SettingsSection } from './settings-layout';

export function SystemPreflight() {
  const { t, i18n } = useTranslation();
  const query = useQuery({
    queryKey: ['setup-preflight'],
    queryFn: ({ signal }) => apiJson<PreflightReport>('/setup/preflight', { signal }),
    enabled: false,
    retry: false,
  });
  const checks = Array.isArray(query.data?.checks) ? query.data.checks : [];
  // The backend sends English text plus a structured variant (key + values).
  // Checks it marks with a catalog variant are shown from the translation
  // catalog instead; anything the catalog does not cover (unknown ids,
  // newer backend variants) falls back to the English text, so a row is
  // never rendered as a raw i18n key.
  const localized = (check: (typeof checks)[number]) => {
    const variant = check.key && check.key !== 'default' ? `_${check.key}` : '';
    const base = `setup.check_${check.id}${variant}`;
    if (i18n.exists(`${base}_detail`)) {
      const values = check.values ?? {};
      return {
        label:
          i18n.exists(`${base}_label`)
            ? t(`${base}_label`, values)
            : i18n.exists(`setup.check_${check.id}_label`)
              ? t(`setup.check_${check.id}_label`, values)
              : check.label,
        detail: t(`${base}_detail`, values),
        fix: check.fix
          ? i18n.exists(`${base}_fix`)
            ? t(`${base}_fix`, values)
            : check.fix
          : check.fix,
      };
    }
    if (check.id === 'arch') {
      // Legacy shape: the arch check predates structured variants.
      return {
        label: t('setup.check_arch_label'),
        detail: t('setup.check_arch_detail'),
        fix: t('setup.check_arch_fix'),
      };
    }
    return { label: check.label, detail: check.detail, fix: check.fix };
  };
  return (
    <SettingsSection title={t('setup.system_preflight')} icon={ScanSearchIcon}>
      <SettingsRow
        id="system-preflight-check"
        title={t('setup.system_check')}
        description={t('setup.system_check_desc')}
      >
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          {t(
            query.isFetching
              ? 'setup.probing'
              : query.data
                ? 'setup.recheck'
                : 'setup.system_check',
          )}
        </Button>
      </SettingsRow>
      {query.isError && (
        <p role="alert" className="px-4 py-3 text-sm text-destructive">
          {t('backend.retry')}
        </p>
      )}
      {checks.length > 0 && (
        <ul className="divide-y divide-border/50 px-4">
          {checks.map((check) => {
            const Icon =
              check.status === 'pass'
                ? CheckCircleIcon
                : check.status === 'warn'
                  ? TriangleAlertIcon
                  : CircleXIcon;
            const text = localized(check);
            return (
              <li key={check.id} className="flex items-start gap-3 py-3">
                <Icon
                  aria-hidden="true"
                  className={
                    'mt-0.5 size-4 shrink-0 ' +
                    (check.status === 'pass'
                      ? 'text-success'
                      : check.status === 'warn'
                        ? 'text-warning'
                        : 'text-destructive')
                  }
                />
                <div className="min-w-0 space-y-1">
                  <h3 className="text-sm font-medium">{text.label}</h3>
                  <p className="break-words text-xs leading-5 text-muted-foreground">
                    {text.detail}
                  </p>
                  {text.fix && <p className="break-words text-xs leading-5">{text.fix}</p>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </SettingsSection>
  );
}
