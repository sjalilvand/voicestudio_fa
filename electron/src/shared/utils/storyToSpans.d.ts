export function storyToSpans(
  tracks: { text: string; profileId?: string | null; character?: string; speed?: number | null }[],
  cast: { id: string; profileId: string | null }[],
  globalSpeed?: number | null,
): {
  title: string;
  // CLEAN-ROOM (spec G-jaketame-1 §4): the span type also carries an optional `join` marker.
  spans: { voice_id: string | null; text: string; pause_ms_after: number; speed?: number | null }[];
}[];
