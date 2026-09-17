import { expect, it } from 'vitest';
import { importToText } from '../../../../../../frontend/src/utils/importStory';
import { splitIntoChunks } from '../../../../../../frontend/src/utils/splitStoryText';
it('removes SRT metadata and retains spoken lines', () => {
  expect(
    importToText(
      'captions.SRT',
      '1\n00:00:01,000 --> 00:00:02,000\nFirst cue\n\n2\n00:00:02,000 --> 00:00:03,000\nSecond cue',
    ),
  ).toBe('First cue\nSecond cue');
});
it('splits locally with bounded chunks and stable text order', () => {
  const text = 'This is the first sentence of the story. This is the second sentence of the story.';
  const chunks = splitIntoChunks(text, 40);
  expect(chunks.every((chunk) => chunk.length <= 40)).toBe(true);
  expect(chunks.join(' ')).toBe(text);
  expect(splitIntoChunks('', 500)).toEqual([]);
});
