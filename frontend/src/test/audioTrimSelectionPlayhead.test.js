import { describe, it, expect } from 'vitest';
import { selectionPlayhead } from '../utils/audioTrim.js';

// The preview playhead must live on the SAME [start,end] buffer timeline as the
// waveform and the exported slice — never a second media-element timeline that
// can drift for VBR / mis-reported-duration files (#1210).
describe('selectionPlayhead', () => {
  it('reports the elapsed offset inside a non-looping selection', () => {
    expect(selectionPlayhead(2, 6, 0, false)).toBe(2);
    expect(selectionPlayhead(2, 6, 1.5, false)).toBeCloseTo(3.5, 6);
  });

  it('clamps at the selection end when not looping', () => {
    expect(selectionPlayhead(2, 6, 10, false)).toBe(6);
  });

  it('wraps within the selection window when looping', () => {
    expect(selectionPlayhead(2, 6, 0, true)).toBe(2);
    expect(selectionPlayhead(2, 6, 5, true)).toBeCloseTo(3, 6); // 5 % 4 = 1 -> 2+1
    expect(selectionPlayhead(2, 6, 4, true)).toBeCloseTo(2, 6); // exact wrap
  });

  it('never divides by zero on a degenerate selection', () => {
    expect(Number.isFinite(selectionPlayhead(3, 3, 2, true))).toBe(true);
    expect(selectionPlayhead(3, 3, 2, false)).toBe(3);
  });
});
