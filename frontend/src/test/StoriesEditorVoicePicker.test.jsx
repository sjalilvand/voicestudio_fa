import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '../i18n';

// The Stories cast + per-line pickers migrated from native <select>s to the
// shared, gallery-enabled VoiceSelector (#1220). VoiceSelector reads /archetypes
// and materializes gallery picks — mock both so the editor renders standalone.
vi.mock('../api/hooks', () => ({ useArchetypes: vi.fn(() => ({ data: undefined })) }));
vi.mock('../api/archetypes', () => ({ useArchetypeAsProfile: vi.fn() }));

import StoriesEditor from '../components/StoriesEditor';
import { useAppStore } from '../store';

const PROFILES = [{ id: 'p_clone', name: 'Aria' }];

function seedStore() {
  useAppStore.setState({
    cast: [{ id: 'narrator', name: 'Narrator', color: '#b8bb26', profileId: null }],
    storyTracks: [
      {
        id: 1,
        character: 'narrator',
        text: 'Once upon a time',
        profileId: null,
        emotion: null,
        speed: null,
        generating: false,
        audioUrl: null,
      },
    ],
    storyProjects: [],
    currentProjectId: null,
  });
}

function renderEditor() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <StoriesEditor profiles={PROFILES} />
    </QueryClientProvider>,
  );
}

describe('StoriesEditor voice pickers (#1220)', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    seedStore();
  });

  it('per-line picker renders VoiceSelector and stores the picked profile id', () => {
    renderEditor();
    const list = screen.getByRole('list');
    // The line-card voice picker trigger shows the default label.
    const trigger = within(list).getByRole('button', { name: /Default/ });
    fireEvent.click(trigger);
    fireEvent.mouseDown(screen.getByText('Aria'));
    expect(useAppStore.getState().storyTracks[0].profileId).toBe('p_clone');
  });

  it('cast picker renders VoiceSelector and stores the character voice', () => {
    renderEditor();
    const castRegion = screen.getByRole('complementary', { name: /Stories/ });
    const trigger = within(castRegion).getByRole('button', { name: /Default/ });
    fireEvent.click(trigger);
    fireEvent.mouseDown(screen.getByText('Aria'));
    expect(useAppStore.getState().cast[0].profileId).toBe('p_clone');
  });

  it('renders a calm writing hierarchy with the project stats and line canvas', () => {
    renderEditor();
    expect(screen.getByRole('heading', { level: 1, name: /Untitled story/ })).toBeInTheDocument();
    expect(screen.getAllByText('1 lines').length).toBeGreaterThan(0);
    expect(screen.getByRole('main')).toHaveClass('stories-manuscript');
    expect(screen.getByRole('complementary')).toHaveClass('stories-sidebar');
    expect(screen.getByRole('list')).toHaveClass('stories-track-list');
    expect(screen.getByRole('listitem')).toHaveClass('stories-line');
  });

  it('loads a comprehensive working sample by default', async () => {
    useAppStore.setState({ storyTracks: [], storyProjects: [], currentProjectId: null });
    renderEditor();

    await waitFor(() => expect(useAppStore.getState().storyTracks).toHaveLength(11));
    const state = useAppStore.getState();
    expect(state.cast.map((member) => member.name)).toEqual(['Narrator', 'Mara', 'Cole']);
    expect(state.cast.every((member) => member.profileId === 'p_clone')).toBe(true);
    expect(state.storyProjects.at(-1)?.name).toBe("The Lighthouse at Wits' End");
    expect(
      screen.getByRole('heading', { name: "The Lighthouse at Wits' End" }),
    ).toBeInTheDocument();
    expect(state.storyTracks.filter((track) => track.text.startsWith('#'))).toHaveLength(2);
    expect(state.storyTracks.some((track) => track.text.includes('[pause'))).toBe(true);
  });

  it('does not restore sample voices after the user clears them', async () => {
    useAppStore.setState({ storyTracks: [], storyProjects: [], currentProjectId: null });
    renderEditor();
    await waitFor(() => expect(useAppStore.getState().storyTracks).toHaveLength(11));

    act(() => {
      useAppStore
        .getState()
        .setCast(useAppStore.getState().cast.map((member) => ({ ...member, profileId: null })));
    });
    await act(async () => {});

    expect(useAppStore.getState().cast.every((member) => member.profileId === null)).toBe(true);
  });

  it('makes only the drag handle draggable so text remains selectable', () => {
    const { container } = renderEditor();
    const row = screen.getByRole('listitem');

    expect(row).not.toHaveAttribute('draggable');
    expect(within(row).getByRole('textbox')).not.toHaveAttribute('draggable');
    expect(container.querySelector('.stories-line__drag')).toHaveAttribute('draggable', 'true');
  });
});
