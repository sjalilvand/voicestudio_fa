import { beforeEach, expect, it, vi } from 'vitest';
import type { GenerateResult } from '@/lib/api/types';
import { clearLatestOutput, outputStore, setLatestOutput } from './output';

const createObjectURL = vi.fn(() => `blob:take-${createObjectURL.mock.calls.length}`);
const revokeObjectURL = vi.fn();

function result(id: string): GenerateResult {
  return {
    blob: new Blob([id], { type: 'audio/wav' }),
    id,
    audioPath: `${id}.wav`,
    durationSeconds: 1,
    genTimeSeconds: 2,
    seed: 3,
    routing: null,
    dropped: null,
  };
}

beforeEach(() => {
  Object.assign(URL, { createObjectURL, revokeObjectURL });
  clearLatestOutput();
  createObjectURL.mockClear();
  revokeObjectURL.mockClear();
});

it('retains earlier session takes until the output history is cleared', () => {
  setLatestOutput(result('first'), 'First');
  const firstUrl = outputStore.state.objectUrl;
  setLatestOutput(result('second'), 'Second');

  expect(outputStore.state.takes.map((take) => take.result.id)).toEqual(['second', 'first']);
  expect(revokeObjectURL).not.toHaveBeenCalledWith(firstUrl);

  clearLatestOutput();
  expect(revokeObjectURL).toHaveBeenCalledWith(firstUrl);
  expect(outputStore.state.takes).toEqual([]);
});
