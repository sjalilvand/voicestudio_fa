import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '../i18n';

// Stories → Clear script removes every line and chapter in one confirmed
// step. Before it existed an imported story could only be undone one trash
// icon at a time, and the cast must survive the clear.

vi.mock('../api/generate', () => ({ generateSpeech: vi.fn(), audioUrl: (path) => path }));
vi.mock('../utils/media', () => ({ playBlobAudio: vi.fn(() => Promise.resolve()), isTauri: false }));
vi.mock('../api/hooks', () => ({ useArchetypes: vi.fn(() => ({ data: undefined })) }));
vi.mock('../api/archetypes', () => ({ useArchetypeAsProfile: vi.fn() }));
const askConfirm = vi.fn();
vi.mock('../utils/dialog', () => ({ askConfirm: (...args) => askConfirm(...args) }));

import StoriesEditor from '../components/StoriesEditor';
import { useAppStore } from '../store';

const CAST = [{ id: 'narrator', name: 'Narrator', color: '#b8bb26', profileId: null }];
const TRACKS = [
  { id: 't1', castId: 'narrator', text: '# Chapter one', voice: null },
  { id: 't2', castId: 'narrator', text: 'Zoe stepped closer.', voice: null },
  { id: 't3', castId: 'narrator', text: 'It is a sloth!', voice: null },
];

function renderEditor() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <StoriesEditor profiles={[]} />
    </QueryClientProvider>,
  );
}

describe('StoriesEditor clear script', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    askConfirm.mockReset();
    useAppStore.setState({ cast: CAST, storyTracks: TRACKS, storyProjects: [], currentProjectId: null });
  });

  afterEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    window.localStorage.clear();
  });

  it('removes every line after the user confirms, keeps the cast, and does not reseed the sample', async () => {
    // First-run flag deliberately unset: an import-then-clear on a fresh
    // install must end with an empty script, not the demo story.
    askConfirm.mockResolvedValue(true);
    renderEditor();
    fireEvent.click(screen.getByRole('button', { name: /clear script/i }));

    await waitFor(() => expect(useAppStore.getState().storyTracks).toEqual([]));
    expect(askConfirm).toHaveBeenCalledTimes(1);
    expect(askConfirm.mock.calls[0][0]).toMatch(/3 lines/);
    expect(useAppStore.getState().cast).toEqual(CAST);
    await new Promise((r) => setTimeout(r, 50));
    expect(useAppStore.getState().storyTracks).toEqual([]);
    expect(window.localStorage.getItem('ov_stories_default_sample_v2')).toBe('1');
  });

  it('keeps the script when the confirmation is declined', async () => {
    askConfirm.mockResolvedValue(false);
    renderEditor();
    fireEvent.click(screen.getByRole('button', { name: /clear script/i }));

    await waitFor(() => expect(askConfirm).toHaveBeenCalledTimes(1));
    expect(useAppStore.getState().storyTracks).toEqual(TRACKS);
  });

  it('is disabled when the script is already empty', () => {
    // Returning user (sample already shown once), empty project.
    window.localStorage.setItem('ov_stories_default_sample_v2', '1');
    useAppStore.setState({ storyTracks: [] });
    renderEditor();
    expect(screen.getByRole('button', { name: /clear script/i })).toBeDisabled();
    expect(askConfirm).not.toHaveBeenCalled();
  });
});
