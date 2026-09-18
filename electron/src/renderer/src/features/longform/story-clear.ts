import type { Draft, Mode } from './longform-session';

/** What "Clear script" empties: every Stories line (cast kept) or the Audiobook manuscript. */
export function clearedScriptPatch(mode: Mode): Partial<Draft> {
  return mode === 'audiobook' ? { script: '' } : { lines: [], importText: '' };
}

/** How much a clear would remove — drives the button's disabled state and the confirm copy. */
export function scriptSize(mode: Mode, draft: Draft): number {
  return mode === 'audiobook' ? (draft.script.trim() ? 1 : 0) : draft.lines.length;
}
