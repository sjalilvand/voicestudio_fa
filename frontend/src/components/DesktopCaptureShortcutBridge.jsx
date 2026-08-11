import { useEffect } from 'react';
import { emit } from '@tauri-apps/api/event';

/** Focused-window fallback for desktop environments whose global shortcut
 * backend reports registration success but never delivers press events. */
export default function DesktopCaptureShortcutBridge() {
  useEffect(() => {
    if (typeof window === 'undefined' || !('__TAURI_INTERNALS__' in window)) return;

    const isCaptureCombo = (event) =>
      (event.ctrlKey || event.metaKey) && event.shiftKey && event.code === 'Space';

    const forward = (name) => {
      try {
        Promise.resolve(emit(name)).catch((error) =>
          console.warn(`${name} fallback emit failed:`, error),
        );
      } catch (error) {
        console.warn(`${name} fallback emit failed:`, error);
      }
    };

    const onKeyDown = (event) => {
      if (!isCaptureCombo(event) || event.repeat) return;
      event.preventDefault();
      forward('tray-dictate');
    };
    const onKeyUp = (event) => {
      if (!isCaptureCombo(event)) return;
      event.preventDefault();
      forward('tray-dictate-stop');
    };

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, []);

  return null;
}
