export interface Overrides {
  numStep: number | null;
  guidanceScale: number | null;
  posTemp: number | null;
  classTemp: number | null;
  postprocess: boolean | null;
  seed: number | null;
  varyRepeats: boolean;
  emoText: string;
  emoAlpha: number | null;
  // CLEAN-ROOM (spec G-jaketame-1 §6): lineGapMs, paragraphGapMs and trimEdges belong here.
}
export const DEFAULT_OVERRIDES: Overrides;
export function overridesToRequest(
  overrides: Overrides | null,
  language?: string,
): Record<string, string | number | boolean>;
