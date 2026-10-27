import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { LongformActivityCard } from '@/components/longform-activity-card';
import { cn } from '@/lib/utils';
import { GenerationProgress } from './generation-progress';
import type { GenerateBlocker } from './generate-blocker';
import type { AudiobookRenderChapter } from './longform-session';
import type { RenderProgressSnapshot } from './render-eta';

export interface GenerateSession {
  active: 'stories' | 'audiobook' | null;
  stage: string;
  completed: number;
  total: number;
  failed: number;
  stopped: boolean;
  chapters: AudiobookRenderChapter[];
  progress?: RenderProgressSnapshot | null;
  startedAt?: number | null;
  lastActivityAt?: number | null;
}

const STATUS_ID = 'generate-status';

/** One line saying what the render is doing, or why it cannot start. */
function statusLine(
  t: TFunction,
  session: GenerateSession,
  mine: boolean,
  blocker: GenerateBlocker | null,
): string {
  if (!mine) return blocker ? t(`audiobook.blocked.${blocker}`) : '';
  switch (session.stage) {
    case 'assembling':
      return t('audiobook.assembling');
    case 'starting':
      return t('common.loading');
    default:
      return t('audiobook.progress_summary', {
        current: Math.min(session.completed + 1, session.total),
        total: session.total,
      });
  }
}

function Note({ children }: { children: string }) {
  return (
    <p role="status" aria-live="polite" className="shrink-0 text-xs text-muted-foreground">
      {children}
    </p>
  );
}

// CLEAN-ROOM (spec W7-frontend §2): exported GeneratePanel component goes here.
