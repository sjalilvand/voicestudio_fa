import { Store } from '@tanstack/store';
import { useStore } from '@tanstack/react-store';
import type { GenerateResult } from '@/lib/api/types';
import { createObjectUrl, revokeObjectUrl } from '@/lib/audio/object-url';

export interface OutputState {
  result: GenerateResult | null;
  /** Object URL for `result.blob`, ready for `<audio src>` / waveform rendering. */
  objectUrl: string | null;
  /** The script that produced `result`. */
  text: string;
  /** Recent takes from this synthesis session, newest first. */
  takes: OutputTake[];
}

export interface OutputTake {
  result: GenerateResult;
  objectUrl: string | null;
  text: string;
}

const MAX_SESSION_TAKES = 10;

export const outputStore = new Store<OutputState>({
  result: null,
  objectUrl: null,
  text: '',
  takes: [],
});

export function useLatestOutput(): OutputState {
  return useStore(outputStore);
}

export function setLatestOutput(result: GenerateResult, text: string): void {
  const take = { result, objectUrl: createObjectUrl(result.blob), text };
  outputStore.setState((state) => {
    const takes = [take, ...state.takes];
    for (const dropped of takes.slice(MAX_SESSION_TAKES)) revokeObjectUrl(dropped.objectUrl);
    return { ...take, takes: takes.slice(0, MAX_SESSION_TAKES) };
  });
}

export function clearLatestOutput(): void {
  for (const take of outputStore.state.takes) revokeObjectUrl(take.objectUrl);
  outputStore.setState(() => ({ result: null, objectUrl: null, text: '', takes: [] }));
}
