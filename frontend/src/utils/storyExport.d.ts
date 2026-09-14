interface Track { text: string; character?: string; profileId?: string | null; speed?: number | null }
export function isChapterLine(text: string): boolean;
export function chapterTitle(text: string): string;
export function exportStoryAudio<T extends Track>(tracks: T[], resolve: (track: T) => { profileId: string | null; speed: number | null }, fetchChunk: (text: string, profileId: string | null, speed: number | null) => Promise<Blob>, progress?: ((done: number, total: number) => void) | null): Promise<{ blob: Blob; durationSec: number; chapters: { time: number; title: string }[] }>;
export function exportStems<T extends Track>(tracks: T[], resolve: (track: T) => { profileId: string | null; speed: number | null }, fetchChunk: (text: string, profileId: string | null, speed: number | null) => Promise<Blob>, progress?: ((done: number, total: number) => void) | null): Promise<{ character: string; blob: Blob }[]>;
