// Shared "save this rendered file to disk" util — the ONE place that decides
// how a finished media file leaves the app, on every platform.
//
// Why this exists (#1218): a raw `<a href={httpMediaUrl} download>` does NOT
// download in the Tauri desktop WebView. WebKit (macOS/WKWebView) "handles the
// load" for any media URL its engine can play by NAVIGATING the whole webview
// to the file and playing it fullscreen — replacing the app. The blank-window
// guard then reloads and eventually paints its failure page. So server media
// must never be reached via `<a download>` inside the shell.
//
// The parity-safe route, ported from App.jsx's `triggerDownload`:
//   * Tauri  → native save dialog (`plugin-dialog.save`) → server-side copy so
//              the bytes actually land on disk at the user's chosen path. WebKit
//              silently drops blob downloads too, so a blob is not sufficient.
//   * Browser/Docker → `browserDownload` (fetch → blob → temporary <a download>),
//              which is correct outside the shell.
//
// Two Tauri copy mechanisms, picked by the caller's knowledge of the source:
//   (a) `sourceFilename` set → the file already lives in OUTPUTS_DIR (audiobook
//       / story renders, served at /audio/<file>): copy it via the /export API
//       (`exportAction`), which resolves the name inside OUTPUTS_DIR and copies
//       to the destination. The /audio mount is a StaticFiles mount with no
//       ?save_path= support, so this is the only server-side copy that works
//       for those files.
//   (b) no `sourceFilename` → a dynamic, save_path-aware endpoint (dub exports):
//       append ?save_path= and let that endpoint render + copy, returning JSON.
//   Subtitles (srt/vtt) are small text bodies fetched raw and written via the
//   trusted `save_text_file` command — the backend never handles their dest
//   path (#309).
import { toast } from 'react-hot-toast';
import i18n from '../i18n';
import { isTauri } from './media';
import { apiFetch } from '../api/client';
import { browserDownload } from './download';
import { exportAction, exportRecord } from '../api/exports';

const VIDEO_EXTS = ['mp4', 'mov', 'mkv', 'webm'];
const AUDIO_EXTS = ['wav', 'mp3', 'flac', 'm4b', 'm4a', 'aac', 'ogg', 'opus'];

function guessMode(ext) {
  if (VIDEO_EXTS.includes(ext)) return 'video';
  if (AUDIO_EXTS.includes(ext)) return 'audio';
  return 'file';
}

/**
 * Save a server-rendered media file to disk without ever navigating the
 * webview. Works in the Tauri shell (native dialog + server-side copy) and in
 * the browser/Docker build (blob download). Shows the same user-facing toasts
 * as the App's own export flow. Never creates an `<a href={httpUrl} download>`.
 *
 * @param {string} url            HTTP URL of the file (also the source for the
 *                                browser blob download + dynamic save_path copy).
 * @param {string} fallbackName   Suggested filename in the save dialog / for the
 *                                download.
 * @param {object} [opts]
 * @param {string} [opts.sourceFilename] Basename of a file in OUTPUTS_DIR — when
 *                                set, the Tauri copy goes through `exportAction`
 *                                (/export) instead of a ?save_path= append.
 * @param {() => void} [opts.onValueMoment]   Fires once on a successful save
 *                                (App wires `recordValueMoment('export')`).
 * @param {() => void} [opts.onHistoryChanged] Fires after the export-history
 *                                row is written (App wires `loadExportHistory`).
 */
export async function downloadMedia(url, fallbackName, opts = {}) {
  const { sourceFilename = null, onValueMoment = null, onHistoryChanged = null } = opts;
  const extGuess = (
    fallbackName.includes('.') ? fallbackName.split('.').pop() : 'bin'
  ).toLowerCase();
  const modeGuess = guessMode(extGuess);

  // exportRecord writes the history row for paths the backend didn't already
  // record (browser download, save_path, subtitle). Non-fatal: a failed record
  // must not turn a successful save into an error toast.
  const recordHistory = async (filename, destinationPath) => {
    try {
      await exportRecord({ filename, destination_path: destinationPath, mode: modeGuess });
      onHistoryChanged?.();
    } catch (err) {
      console.warn('exportRecord failed:', err);
    }
  };

  // ── Tauri: native save dialog + server-side copy ────────────────────────
  if (isTauri) {
    try {
      const { save } = await import('@tauri-apps/plugin-dialog');
      const destPath = await save({
        defaultPath: fallbackName,
        filters: [{ name: modeGuess === 'video' ? 'Video' : 'Audio', extensions: [extGuess] }],
      });
      if (!destPath) return; // user cancelled
      toast.loading(i18n.t('app.toast_saving', { name: fallbackName }), { id: fallbackName });

      // (a) File already in OUTPUTS_DIR — copy by source filename via /export.
      // /export records its own history row, so no exportRecord here.
      if (sourceFilename) {
        await exportAction({
          source_filename: sourceFilename,
          destination_path: destPath,
          mode: modeGuess,
        });
        toast.success(i18n.t('app.toast_saved', { path: destPath }), { id: fallbackName });
        onValueMoment?.();
        onHistoryChanged?.();
        return;
      }

      // (b) Subtitles: fetch the small text body and write it from this trusted
      // process — the backend never handles the destination path (#309).
      if (['srt', 'vtt'].includes(extGuess)) {
        const res = await apiFetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`); // don't write an error body to disk
        const text = await res.text();
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('save_text_file', { path: destPath, contents: text });
        toast.success(i18n.t('app.toast_saved', { path: destPath }), { id: fallbackName });
        onValueMoment?.();
        await recordHistory(fallbackName, destPath);
        return;
      }

      // (c) Dynamic save_path-aware endpoint (dub exports): the endpoint copies
      // to destPath and returns a JSON envelope. Guard the content-type so a
      // raw-body response surfaces a clear error, not a JSON.parse crash (#309).
      const sep = url.includes('?') ? '&' : '?';
      const res = await apiFetch(`${url}${sep}save_path=${encodeURIComponent(destPath)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`); // a 4xx/5xx isn't a successful save
      const ctype = res.headers.get('content-type') || '';
      if (!ctype.includes('application/json')) {
        throw new Error(
          `Server returned ${ctype || 'an unknown content type'} instead of a JSON save confirmation`,
        );
      }
      const data = await res.json();
      toast.success(i18n.t('app.toast_saved', { path: data.path }), { id: fallbackName });
      onValueMoment?.();
      await recordHistory(data.display_name || fallbackName, data.path);
    } catch (err) {
      console.error(err);
      toast.error(i18n.t('app.toast_save_error', { message: err.message }), { id: fallbackName });
    }
    return;
  }

  // ── Browser / Docker: standard blob download ────────────────────────────
  try {
    toast.loading(i18n.t('app.toast_processing', { name: fallbackName }), { id: fallbackName });
    const finalName = await browserDownload(url, fallbackName);
    toast.success(i18n.t('app.toast_downloaded', { name: finalName }), { id: fallbackName });
    onValueMoment?.();
    await recordHistory(finalName, `~/Downloads/${finalName}`);
  } catch (err) {
    console.error(err);
    toast.error(i18n.t('app.toast_download_error', { message: err.message }), { id: fallbackName });
  }
}
