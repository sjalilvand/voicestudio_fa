interface Track {
  text: string;
  character?: string;
  profileId?: string | null;
  speed?: number | null;
}
// CLEAN-ROOM (spec O-shivendra-3 §10): Cue and RenderedChapter interfaces go here.
export function isChapterLine(text: string): boolean;
export function chapterTitle(text: string): string;
export function formatTimecode(sec: number): string;
// CLEAN-ROOM (spec O-shivendra-3 §10): declarations for buildCueSheet, cuesFromChapters and cueSheetFilename go here.
export function exportStoryAudio<T extends Track>(
  tracks: T[],
  resolve: (track: T) => { profileId: string | null; speed: number | null },
  fetchChunk: (text: string, profileId: string | null, speed: number | null) => Promise<Blob>,
  progress?: ((done: number, total: number) => void) | null,
): Promise<{ blob: Blob; durationSec: number; chapters: { time: number; title: string }[] }>;
export function exportStems<T extends Track>(
  tracks: T[],
  resolve: (track: T) => { profileId: string | null; speed: number | null },
  fetchChunk: (text: string, profileId: string | null, speed: number | null) => Promise<Blob>,
  progress?: ((done: number, total: number) => void) | null,
): Promise<{ character: string; blob: Blob }[]>;
