import { Fragment } from 'react';
import { useTranslation } from 'react-i18next';

export interface RenderSummary {
  engine?: string;
  voices?: { id: string; name: string }[];
  language?: string;
  format?: string;
  lines?: number;
  words?: number;
  speeds?: number[];
  options?: Record<string, unknown>;
  chapter_titles?: string[];
}

export interface RenderRecord {
  job_id: string;
  title?: string;
  output: string;
  type?: 'story' | 'audiobook';
  created_at?: number | string;
  duration_s?: number;
  chapters?: number;
  summary?: RenderSummary;
}

const OPTION_LABELS: Record<string, string> = {
  num_step: 'clone.steps',
  guidance_scale: 'clone.cfg',
  position_temperature: 'clone.pos_temp',
  class_temperature: 'clone.class_temp',
  postprocess_output: 'clone.postprocess',
  seed: 'audiobook.seed',
  emo_vector: 'audiobook.emotion_help',
  emo_text: 'audiobook.emotion_text',
  emo_alpha: 'audiobook.emotion_alpha',
  vary_repeats: 'audiobook.vary_repeats',
  line_gap_ms: 'audiobook.line_gap',
  paragraph_gap_ms: 'audiobook.paragraph_gap',
  trim_edges: 'audiobook.trim_edges',
};

/** Format seconds as m:ss, switching to h:mm:ss at one hour. */
export function clock(seconds?: number): string {
  const numeric = Number(seconds);
  const total = Math.max(0, Math.round(Number.isFinite(numeric) ? numeric : 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
    : `${minutes}:${String(remainder).padStart(2, '0')}`;
}

/** `1.00×` for one speed, `0.90–1.25×` for a range, nothing without usable values. */
export function speedLabel(speeds: unknown): string {
  if (!Array.isArray(speeds)) return '';
  const finite = speeds.filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  if (!finite.length) return '';
  const low = Math.min(...finite).toFixed(2);
  const high = Math.max(...finite).toFixed(2);
  return low === high ? `${low}×` : `${low}–${high}×`;
}

/** Voice names (id when a name is blank) joined by commas. */
export function voiceLabel(summary?: RenderSummary): string {
  const voices: unknown = summary?.voices;
  if (!Array.isArray(voices)) return '';
  return voices
    .map((voice: { id?: string; name?: string } | null) =>
      voice && typeof voice === 'object' ? voice.name || voice.id || '' : '',
    )
    .filter(Boolean)
    .join(', ');
}

// CLEAN-ROOM (spec W7-frontend §3): exported renderRecipe(render) one-line summary goes here.

// CLEAN-ROOM (spec W7-frontend §4): exported RenderDetails component goes here.

/** Collapsible "how it was made" block for a Projects row. */
export function RenderDisclosure({ render }: { render: RenderRecord }) {
  const { t } = useTranslation();
  return (
    <details className="group mt-1.5">
      <summary className="w-fit cursor-pointer select-none text-xs text-muted-foreground underline-offset-2 hover:underline">
        {t('projects.render_details')}
      </summary>
      <RenderDetails render={render} />
    </details>
  );
}
