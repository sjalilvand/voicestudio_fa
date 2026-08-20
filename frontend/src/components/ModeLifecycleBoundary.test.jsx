import { useLayoutEffect, useRef } from 'react';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ModeLifecycleBoundary from './ModeLifecycleBoundary';

function ImperativeWorkspace({ name }) {
  const hostRef = useRef(null);

  useLayoutEffect(() => {
    const owned = document.createElement('div');
    owned.dataset.owner = name;
    hostRef.current.appendChild(owned);
    return () => owned.remove();
  }, [name]);

  return <section ref={hostRef}>{name}</section>;
}

describe('ModeLifecycleBoundary', () => {
  it('replaces the DOM owner throughout the reported rapid navigation loop', () => {
    const sequence = ['launchpad', 'dub', 'dub', 'launchpad', 'dub'];
    const view = render(
      <ModeLifecycleBoundary mode={sequence[0]}>
        <ImperativeWorkspace name={sequence[0]} />
      </ModeLifecycleBoundary>,
    );
    let previousHost = view.container.firstElementChild;
    let previousMode = sequence[0];

    for (const mode of sequence.slice(1)) {
      view.rerender(
        <ModeLifecycleBoundary mode={mode}>
          <ImperativeWorkspace name={mode} />
        </ModeLifecycleBoundary>,
      );
      const nextHost = view.container.firstElementChild;
      if (mode !== previousMode) {
        expect(nextHost).not.toBe(previousHost);
        expect(previousHost.isConnected).toBe(false);
      } else {
        expect(nextHost).toBe(previousHost);
      }
      expect(nextHost.querySelector('[data-owner]')?.dataset.owner).toBe(mode);
      previousHost = nextHost;
      previousMode = mode;
    }
  });
});
