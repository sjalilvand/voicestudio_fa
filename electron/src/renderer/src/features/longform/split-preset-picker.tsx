import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { SPLIT_MODES, type SplitMode } from '@shared/utils/splitStoryText';

const CHAR_FLOOR = 40;
const CHAR_CEIL = 2000;

interface PickerProps {
  preset: SplitMode;
  onPreset: (next: SplitMode) => void;
  charLimit: number;
  onCharLimit: (next: number) => void;
  disabled?: boolean;
}

/** Preset menu for Paste & Split; the character cap only matters for sentence splitting. */
export function SplitPresetPicker({
  preset,
  onPreset,
  charLimit,
  onCharLimit,
  disabled,
}: PickerProps) {
  const { t } = useTranslation();
  const entries = SPLIT_MODES.map((value) => ({ value, label: t(`stories.split_${value}`) }));
  return (
    <div className="ml-auto flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
      <Select
        items={entries}
        value={preset}
        disabled={disabled}
        onValueChange={(v) => onPreset(v as SplitMode)}
      >
        <SelectTrigger size="sm" aria-label={t('stories.splitMode')}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="end">
          {entries.map((e) => (
            <SelectItem key={e.value} value={e.value}>
              {e.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {preset === 'sentences' && (
        <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>{t('stories.maxChars')}</span>
          <Input
            type="number"
            min={CHAR_FLOOR}
            max={CHAR_CEIL}
            step={10}
            className="h-8 w-20"
            disabled={disabled}
            value={charLimit}
            onChange={(e) =>
              onCharLimit(
                Math.min(CHAR_CEIL, Math.max(CHAR_FLOOR, Number(e.target.value) || CHAR_FLOOR)),
              )
            }
          />
        </label>
      )}
    </div>
  );
}
