import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import DubResizableColumns from './DubResizableColumns';

describe('DubResizableColumns', () => {
  beforeEach(() => localStorage.clear());

  it('lets keyboard users enlarge the transcript column and persists the split', () => {
    const { unmount } = render(
      <DubResizableColumns resizeLabel="Resize video and transcript columns">
        <div>Video</div>
        <div>Transcript</div>
      </DubResizableColumns>,
    );
    const separator = screen.getByRole('separator');

    fireEvent.keyDown(separator, { key: 'ArrowLeft' });

    expect(separator).toHaveAttribute('aria-valuenow', '45');
    expect(separator.parentElement).toHaveStyle({ gridTemplateColumns: '45fr 12px 55fr' });
    unmount();

    render(
      <DubResizableColumns resizeLabel="Resize video and transcript columns">
        <div>Video</div>
        <div>Transcript</div>
      </DubResizableColumns>,
    );
    expect(screen.getByRole('separator')).toHaveAttribute('aria-valuenow', '45');
  });

  it('clamps pointer resizing so both editors remain usable', () => {
    render(
      <DubResizableColumns resizeLabel="Resize video and transcript columns">
        <div>Video</div>
        <div>Transcript</div>
      </DubResizableColumns>,
    );
    const separator = screen.getByRole('separator');
    separator.parentElement.getBoundingClientRect = () => ({ left: 100, width: 1000 });

    fireEvent.pointerDown(separator, { pointerId: 1, clientX: 500 });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 50 });
    fireEvent.pointerUp(separator, { pointerId: 1, clientX: 50 });

    expect(separator).toHaveAttribute('aria-valuenow', '25');
  });
});
