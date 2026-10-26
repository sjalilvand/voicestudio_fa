export interface DescriptionResult {
  attrs: Record<string, string>;
  matched: unknown[];
  unmatched: string[];
}
// CLEAN-ROOM (spec T1-folded §9): the ``useDescription`` hook goes here; the
// ``DescriptionResult`` response type above is kept.
