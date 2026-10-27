import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AudioLinesIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { apiJson } from '@/lib/api/client';
import { SettingsRow, SettingsSection } from './settings-layout';
import { useSettingsAction } from './use-settings-action';

const PATH = '/api/settings/pause-fill';
const KEY = ['pause-fill'] as const;

interface PauseFillState {
  mode: 'silence' | 'room_tone';
  env_pinned: boolean;
}

/** #3611: fill [pause] markers and audiobook gaps with room tone instead of digital silence. */
export function PauseFillSettings() {
  const { t } = useTranslation();
  const client = useQueryClient();
  const action = useSettingsAction();
  const query = useQuery({
    queryKey: KEY,
    queryFn: ({ signal }) => apiJson<PauseFillState>(PATH, { signal }),
  });
  const state = query.data;
  return (
    <SettingsSection icon={AudioLinesIcon} title={t('pauseFill.title')}>
      <SettingsRow
        id="pause-fill"
        title={t('pauseFill.room_tone')}
        description={t('pauseFill.room_tone_note')}
      >
        <Switch
          aria-label={t('pauseFill.room_tone')}
          checked={state?.mode === 'room_tone'}
          disabled={!state || action.busy || state.env_pinned}
          onCheckedChange={(on) =>
            void action.run(async () => {
              const saved = await apiJson<PauseFillState>(PATH, {
                method: 'PUT',
                body: JSON.stringify({ mode: on ? 'room_tone' : 'silence' }),
              });
              client.setQueryData(KEY, saved);
            })
          }
        />
      </SettingsRow>
      {state?.env_pinned && (
        <p className="p-4 text-sm text-muted-foreground">
          {t('pauseFill.env_pinned', { env: 'OMNIVOICE_PAUSE_FILL' })}
        </p>
      )}
      {(action.error || query.isError) && (
        <p role="alert" className="p-4 text-sm text-destructive">
          {t('common.error')}{' '}
          <Button size="sm" variant="ghost" onClick={() => void query.refetch()}>
            {t('common.retry')}
          </Button>
        </p>
      )}
    </SettingsSection>
  );
}
