import { describe, it, expect, vi, beforeEach } from 'vitest';

// #1218: `downloadMedia` must save a finished render without ever navigating
// the webview. In the browser it uses `browserDownload`; in Tauri it uses the
// native save dialog + a server-side copy — NEVER an `<a href={httpUrl} download>`
// (which WebKit turns into a fullscreen media navigation that hijacks the app).

const browserDownload = vi.fn(async (_url, name) => name);
const exportAction = vi.fn(async () => ({ success: true }));
const exportRecord = vi.fn(async () => ({ success: true }));
const apiFetch = vi.fn();
const save = vi.fn();
const invoke = vi.fn(async () => {});
const toast = {
  loading: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
};

// Load the util with a chosen isTauri value. resetModules + doMock so both
// branches can be exercised from one file (isTauri is a module-load const).
async function loadDownloadMedia({ tauri }) {
  vi.resetModules();
  vi.doMock('./media', () => ({ isTauri: tauri }));
  vi.doMock('./download', () => ({ browserDownload }));
  vi.doMock('../api/exports', () => ({ exportAction, exportRecord }));
  vi.doMock('../api/client', () => ({ apiFetch }));
  vi.doMock('react-hot-toast', () => ({ toast }));
  vi.doMock('../i18n', () => ({
    default: { t: (key, opts) => `${key}:${JSON.stringify(opts || {})}` },
  }));
  vi.doMock('@tauri-apps/plugin-dialog', () => ({ save }));
  vi.doMock('@tauri-apps/api/core', () => ({ invoke }));
  return (await import('./mediaDownload')).downloadMedia;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('downloadMedia — browser branch (isTauri=false)', () => {
  it('routes through browserDownload and never opens the save dialog or copies server-side', async () => {
    const downloadMedia = await loadDownloadMedia({ tauri: false });
    const onValueMoment = vi.fn();
    const onHistoryChanged = vi.fn();

    await downloadMedia('http://x/audio/foo.m4b', 'foo.m4b', { onValueMoment, onHistoryChanged });

    expect(browserDownload).toHaveBeenCalledWith('http://x/audio/foo.m4b', 'foo.m4b');
    expect(save).not.toHaveBeenCalled(); // no native dialog in the browser
    expect(exportAction).not.toHaveBeenCalled(); // no server-side copy
    // History row still recorded for the browser download, + the callbacks.
    expect(exportRecord).toHaveBeenCalledWith(
      expect.objectContaining({ filename: 'foo.m4b', mode: 'audio' }),
    );
    expect(onValueMoment).toHaveBeenCalledOnce();
    expect(onHistoryChanged).toHaveBeenCalledOnce();
  });
});

describe('downloadMedia — Tauri branch (isTauri=true)', () => {
  it('OUTPUTS_DIR file: opens the save dialog + copies via exportAction, no blob download, no <a>', async () => {
    const downloadMedia = await loadDownloadMedia({ tauri: true });
    save.mockResolvedValueOnce('/Users/me/Books/foo.m4b');
    const createElement = vi.spyOn(document, 'createElement');
    const onValueMoment = vi.fn();

    await downloadMedia('http://x/audio/foo.m4b', 'foo.m4b', {
      sourceFilename: 'foo.m4b',
      onValueMoment,
    });

    expect(save).toHaveBeenCalledOnce();
    expect(exportAction).toHaveBeenCalledWith({
      source_filename: 'foo.m4b',
      destination_path: '/Users/me/Books/foo.m4b',
      mode: 'audio',
    });
    // The webview-hijack bug was a raw `<a href={httpUrl} download>`; the util
    // must never create one, and must not fall back to the blob download.
    expect(browserDownload).not.toHaveBeenCalled();
    const madeAnchor = createElement.mock.calls.some(([tag]) => tag === 'a');
    expect(madeAnchor).toBe(false);
    // /export records its own history row — no double exportRecord here.
    expect(exportRecord).not.toHaveBeenCalled();
    expect(onValueMoment).toHaveBeenCalledOnce();
    createElement.mockRestore();
  });

  it('cancelled save dialog is a no-op (no copy, no error)', async () => {
    const downloadMedia = await loadDownloadMedia({ tauri: true });
    save.mockResolvedValueOnce(null); // user cancelled

    await downloadMedia('http://x/audio/foo.m4b', 'foo.m4b', { sourceFilename: 'foo.m4b' });

    expect(exportAction).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('dynamic endpoint (no sourceFilename): appends ?save_path= and records history', async () => {
    const downloadMedia = await loadDownloadMedia({ tauri: true });
    save.mockResolvedValueOnce('/Users/me/Movies/dubbed_video.mp4');
    apiFetch.mockResolvedValueOnce({
      ok: true,
      headers: { get: () => 'application/json' },
      json: async () => ({
        path: '/Users/me/Movies/dubbed_video.mp4',
        display_name: 'dubbed_video.mp4',
      }),
    });

    await downloadMedia(
      'http://x/dub/download/job/dubbed_video.mp4?preserve_bg=1',
      'dubbed_video.mp4',
    );

    const fetchedUrl = apiFetch.mock.calls[0][0];
    expect(fetchedUrl).toContain('save_path=');
    expect(fetchedUrl).toContain(encodeURIComponent('/Users/me/Movies/dubbed_video.mp4'));
    expect(exportAction).not.toHaveBeenCalled(); // dynamic endpoint copies itself
    expect(exportRecord).toHaveBeenCalledWith(
      expect.objectContaining({ filename: 'dubbed_video.mp4', mode: 'video' }),
    );
  });
});
