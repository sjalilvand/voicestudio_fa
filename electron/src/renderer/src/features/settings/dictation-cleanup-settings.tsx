import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { apiJson } from '@/lib/api/client';
import { Switch } from '@/components/ui/switch';
import { SettingsSection, SettingsRow } from './settings-layout';

const ENDPOINT = '/api/settings/dictation-refinement';
const QUERY_KEY = ['dictation-refinement'];

interface CleanupConfig {
  spoken_punctuation?: boolean;
}

/** Deterministic dictation cleanup — works without an LLM, unlike refinement. */
export function DictationCleanupSettings() {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const query = useQuery({
    queryKey: QUERY_KEY,
    queryFn: ({ signal }) => apiJson<CleanupConfig>(ENDPOINT, { signal }),
  });
  const update = async (value: boolean) => {
    if (busy) return;
    setBusy(true);
    setError(false);
    try {
      const config = await apiJson<CleanupConfig>(ENDPOINT, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spoken_punctuation: value }),
      });
      client.setQueryData(QUERY_KEY, config);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };
  if (!query.data) return null;
  return (
    <SettingsSection title={t('dictation.cleanup_title')}>
      {error && (
        <p role="alert" className="p-4 text-sm text-destructive">
          {t('common.error')}
        </p>
      )}
      <SettingsRow
        id="dictation-spoken-punctuation"
        title={t('dictation.spoken_punctuation')}
        description={t('dictation.spoken_punctuation_desc')}
      >
        <Switch
          aria-label={t('dictation.spoken_punctuation')}
          checked={Boolean(query.data.spoken_punctuation)}
          disabled={busy}
          onCheckedChange={(value) => void update(value)}
        />
      </SettingsRow>
    </SettingsSection>
  );
}
