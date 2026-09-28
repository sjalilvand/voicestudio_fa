import { useId } from 'react';
import { ChevronDownIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { useEngines } from '@/hooks/use-engines';
import { effectiveSamplingSteps, samplingStepRange } from '@/lib/audio/quality';
import { setCloneSetting, useCloneSettings } from '@/lib/store/clone-settings';

const precisions = [16, 24, 32] as const;

export function QualityControls({ disabled = false }: { disabled?: boolean }) {
  const { t } = useTranslation();
  const settings = useCloneSettings();
  const { activeTts } = useEngines();
  const id = useId();
  const bits = settings.wavBits;
  const rate = activeTts?.output_sample_rate;
  const channels = activeTts?.output_channels;
  const estimatedSize = rate && rate > 0 && channels && channels > 0
    ? ((rate * channels * 60 * bits) / 8 / 1000000).toFixed(1)
    : null;
  const stepRange = samplingStepRange(activeTts?.id);
  const steps = effectiveSamplingSteps(settings.steps, activeTts?.id);
  return (
    <section aria-labelledby={id} className="my-3 shrink-0 border-t border-border/50 pt-3">
      <h3 id={id} className="sr-only">
        {t('cloneQuality.title')}
      </h3>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="min-w-0 flex-1 basis-56 space-y-2">
          <div className="flex flex-wrap justify-between gap-2 text-xs">
            <span id={`${id}-precision`}>{t('cloneQuality.title')}</span>
            <output className="font-medium">{t(`cloneQuality.preset${bits}`)}</output>
          </div>
          <Slider
            thumbProps={{
              'aria-labelledby': `${id}-precision`,
              'aria-describedby': `${id}-size`,
              getAriaValueText: (_formatted, value) => t(`cloneQuality.preset${precisions[value]}`),
            }}
            min={0}
            max={2}
            step={1}
            value={[precisions.indexOf(bits)]}
            disabled={disabled}
            onValueChange={(value) =>
              setCloneSetting('wavBits', precisions[Array.isArray(value) ? value[0] : value])
            }
          />
          <p id={`${id}-size`} className="text-xs text-muted-foreground">
            {estimatedSize ? t('cloneQuality.size', { size: estimatedSize }) : t('cloneQuality.sizeUnknown')}
          </p>
        </div>
      </div>
      <details className="group mt-2">
        <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-xs text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
          {t('voiceControls.options')}
          <ChevronDownIcon
            className="size-3 transition-transform group-open:rotate-180"
            aria-hidden="true"
          />
        </summary>
        <div className="mt-3 grid gap-x-8 gap-y-4 pb-1 sm:grid-cols-2">
          <p className="text-xs text-muted-foreground sm:col-span-2">
            {t(`cloneQuality.bits${bits}`)} · {t(`cloneQuality.hint${bits}`)}
          </p>
          {stepRange && (
            <div className="space-y-2">
              <div className="flex justify-between gap-2 text-xs">
                <span id={`${id}-steps`}>{t('cloneQuality.effort')}</span>
                <output className="tabular-nums">{steps}</output>
              </div>
              <Slider
                thumbProps={{
                  'aria-labelledby': `${id}-steps`,
                  'aria-describedby': `${id}-effort`,
                }}
                min={stepRange[0]}
                max={stepRange[1]}
                step={1}
                value={[steps]}
                disabled={disabled}
                onValueChange={(value) =>
                  setCloneSetting('steps', Array.isArray(value) ? value[0] : value)
                }
              />
              <p id={`${id}-effort`} className="text-xs text-muted-foreground">
                {t('cloneQuality.effortHint')}
              </p>
            </div>
          )}
          <div className="flex items-start justify-between gap-3 text-xs">
            <span>
              {t('cloneQuality.mastering')}
              <span className="mt-1 block text-muted-foreground">
                {t('cloneQuality.masteringHint')}
              </span>
            </span>
            <Switch
              aria-label={t('cloneQuality.mastering')}
              checked={settings.effectPreset === 'broadcast'}
              disabled={disabled}
              onCheckedChange={(checked) =>
                setCloneSetting('effectPreset', checked ? 'broadcast' : 'raw')
              }
            />
          </div>
          <p className="text-xs text-muted-foreground sm:col-span-2">{t('cloneQuality.nextTake')}</p>
        </div>
      </details>
    </section>
  );
}
