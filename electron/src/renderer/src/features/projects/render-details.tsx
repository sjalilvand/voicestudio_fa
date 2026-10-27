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

/** Summarise voice, speed, engine, and length on one line. */
export function renderRecipe(render: RenderRecord): string {
  return [
    voiceLabel(render.summary),
    speedLabel(render.summary?.speeds),
    render.summary?.engine,
    render.duration_s ? clock(render.duration_s) : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

export function RenderDetails({ render }: { render: RenderRecord }) {
  const { t } = useTranslation();
  const summary = render.summary;
  if (!summary) {
    return <p className="mt-2 text-xs text-muted-foreground">{t('projects.render_no_details')}</p>;
  }

  const options =
    summary.options && typeof summary.options === 'object' && !Array.isArray(summary.options)
      ? summary.options
      : {};
  const settings = Object.entries(options)
    .filter(([key]) => Object.prototype.hasOwnProperty.call(OPTION_LABELS, key))
    .map(([key, value]) => {
      const shown =
        typeof value === 'boolean'
          ? t(value ? 'pronunciation.enabled' : 'supportPlans.disabled')
          : String(value);
      return `${t(OPTION_LABELS[key])} ${shown}`;
    })
    .join(' · ');
  const size = t('projects.render_size', {
    chapters: render.chapters ?? summary.chapter_titles?.length ?? 0,
    lines: summary.lines ?? 0,
    words: summary.words ?? 0,
  });
  const candidates = [
    { term: t('projects.render_voice'), detail: voiceLabel(summary) },
    { term: t('projects.render_speed'), detail: speedLabel(summary.speeds) },
    { term: t('projects.render_engine'), detail: summary.engine ?? '' },
    { term: t('projects.render_language'), detail: summary.language ?? '' },
    { term: t('projects.render_format'), detail: summary.format?.toUpperCase() ?? '' },
    { term: t('projects.render_size_label'), detail: size },
    { term: t('projects.render_settings'), detail: settings },
  ];
  const rows = candidates.filter(({ detail }) => detail !== '');

  return (
    <dl className="mt-2 grid grid-cols-[max-content_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1 text-xs">
      {rows.map(({ term, detail }) => (
        <Fragment key={term}>
          <dt className="whitespace-nowrap text-muted-foreground">{term}</dt>
          <dd className="min-w-0 [overflow-wrap:anywhere]">{detail}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

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
