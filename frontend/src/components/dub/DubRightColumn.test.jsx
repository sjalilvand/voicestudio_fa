import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../DubSegmentTable', () => ({ default: () => null }));

import DubRightColumn from './DubRightColumn';

const noop = () => {};

function column(multiBatchBusy, setDubLang = noop, setDubLangCode = noop) {
  return (
    <DubRightColumn
      t={(key) => key}
      preserveBg={false}
      setPreserveBg={noop}
      dualSubs={false}
      setDualSubs={noop}
      burnSubs={false}
      setBurnSubs={noop}
      defaultTrack="original"
      setDefaultTrack={noop}
      dubLangCode="bn"
      multiLangMode
      batchTargets={[
        { lang: 'Bengali', code: 'bn' },
        { lang: 'Spanish', code: 'es' },
      ]}
      multiBatchBusy={multiBatchBusy}
      setDubLang={setDubLang}
      setDubLangCode={setDubLangCode}
      dubTracks={[]}
      timingStrategy="concise"
      setTimingStrategy={noop}
      voiceMatch="per_line"
      setVoiceMatch={noop}
      dubTranscript=""
      showTranscript={false}
      setShowTranscript={noop}
      dubJobId={null}
      glossaryVisible={false}
      selectedSegIds={new Set()}
      speakerClones={{}}
      profiles={[]}
      showCheckpoint={false}
      isTranslating={false}
      dubSegments={[]}
      dubStep="editing"
    />
  );
}

describe('DubRightColumn language targets', () => {
  it('disables language switches for the full shared batch lock', async () => {
    const setDubLang = vi.fn();
    const setDubLangCode = vi.fn();
    let rerender;
    await act(async () => {
      ({ rerender } = render(column(true, setDubLang, setDubLangCode)));
      await Promise.resolve();
    });
    const spanish = screen.getByRole('button', { name: 'ES' });

    expect(spanish).toBeDisabled();
    fireEvent.click(spanish);
    expect(setDubLangCode).not.toHaveBeenCalled();

    await act(async () => {
      rerender(column(false, setDubLang, setDubLangCode));
      await Promise.resolve();
    });
    fireEvent.click(screen.getByRole('button', { name: 'ES' }));
    expect(setDubLang).toHaveBeenCalledWith('Spanish');
    expect(setDubLangCode).toHaveBeenCalledWith('es');
  });
});
