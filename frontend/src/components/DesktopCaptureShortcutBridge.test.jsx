import { fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DesktopCaptureShortcutBridge from './DesktopCaptureShortcutBridge';

const { emit } = vi.hoisted(() => ({ emit: vi.fn() }));
vi.mock('@tauri-apps/api/event', () => ({ emit }));

describe('DesktopCaptureShortcutBridge', () => {
  beforeEach(() => {
    window.__TAURI_INTERNALS__ = {};
    emit.mockReset().mockResolvedValue(undefined);
  });

  afterEach(() => {
    delete window.__TAURI_INTERNALS__;
  });

  it('forwards focused Ctrl+Shift+Space press and release to the widget', async () => {
    render(<DesktopCaptureShortcutBridge />);
    fireEvent.keyDown(window, { code: 'Space', ctrlKey: true, shiftKey: true });
    fireEvent.keyUp(window, { code: 'Space', ctrlKey: true, shiftKey: true });

    await waitFor(() => {
      expect(emit).toHaveBeenCalledWith('tray-dictate');
      expect(emit).toHaveBeenCalledWith('tray-dictate-stop');
    });
  });

  it('ignores auto-repeat and unrelated shortcuts', async () => {
    render(<DesktopCaptureShortcutBridge />);
    fireEvent.keyDown(window, {
      code: 'Space',
      ctrlKey: true,
      shiftKey: true,
      repeat: true,
    });
    fireEvent.keyDown(window, { code: 'Space', ctrlKey: true });
    await Promise.resolve();
    expect(emit).not.toHaveBeenCalled();
  });
});
