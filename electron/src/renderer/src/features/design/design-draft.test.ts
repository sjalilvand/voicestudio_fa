import { beforeEach, describe, expect, it } from 'vitest';
import type { Profile } from '@/lib/api/types';
import {
  canResetToDescription,
  editVoice,
  designRequestSeed,
  linkedDesignProfile,
  pickDetail,
  readDraft,
  replaceRecipe,
  restoreDesignProfile,
  STORAGE,
} from './design-draft';

const profile = {
  id: 'designed-voice',
  name: 'Narrator',
  kind: 'design',
  ref_audio_path: 'preview.wav',
  ref_text: null,
  instruct: 'female, low pitch',
  language: 'French',
  seed: 42,
  personality: null,
  vd_states: JSON.stringify({ Gender: 'male' }),
  created_at: 1,
  is_locked: false,
} satisfies Profile;

describe('designed voice drafts', () => {
  beforeEach(() => localStorage.clear());

  it('restores the native free-form prompt and explicit picks from a saved voice', () => {
    const description = 'a gentle, slightly raspy Japanese narrator';
    const native = {
      ...profile,
      design_recipe: JSON.stringify({
        description,
        picks: { Pitch: 'low pitch' },
        mapped: { Gender: 'female', Age: 'young adult' },
        engine: 'voxcpm2',
      }),
    };
    const restored = restoreDesignProfile(native, 9);
    expect(restored).toMatchObject({
      description,
      profileId: profile.id,
      picks: { Pitch: { value: 'low pitch', description } },
      mapped: { Gender: 'female', Age: 'young adult' },
    });
    const reopened = replaceRecipe(readDraft(), restored);
    expect(reopened.description).toBe(description);
    expect(reopened.profileId).toBe(profile.id);
    expect(designInstruct(reopened, 'freeform')).toBe(description + ', low pitch');
  });

  it('persists the selected profile identity with the draft', () => {
    localStorage.setItem(
      STORAGE,
      JSON.stringify({ text: 'Hello', attrs: { Gender: 'female' }, seed: 7, profileId: 'voice' }),
    );
    expect(readDraft()).toMatchObject({ text: 'Hello', seed: 7, profileId: 'voice' });
  });

  it('restores profile language, seed and a complete recipe without stale values', () => {
    const restored = restoreDesignProfile(profile, 9);
    expect(restored).toMatchObject({
      profileId: 'designed-voice',
      language: 'French',
      seed: 42,
      attrs: { Gender: 'male', Pitch: 'low pitch', Age: 'Auto' },
    });

    expect(
      restoreDesignProfile({ ...profile, vd_states: '{broken', seed: null, language: null }, 9),
    ).toMatchObject({
      language: 'Auto',
      seed: 9,
      attrs: { Gender: 'female', Pitch: 'low pitch' },
    });
  });
});

describe('saved design voice link', () => {
  // A linked draft sends its profile, and the backend re-renders the saved
  // sample. Edits must unlink it, or new attributes, gender and seed are
  // barely heard ("always a female voice", reported on Discord).
  const restored = () => {
    const saved = restoreDesignProfile(profile, 9);
    return replaceRecipe(readDraft(), {
      attrs: saved.attrs,
      seed: saved.seed,
      profileId: saved.profileId,
    });
  };

  it('re-renders the saved voice while the draft is unchanged', () => {
    const draft = restored();
    expect(draft.profileId).toBe('designed-voice');
    expect(linkedDesignProfile(draft, [profile])?.id).toBe('designed-voice');
  });

  it('unlinks on a detail, seed or description edit', () => {
    const draft = restored();
    expect(pickDetail(draft, 'Gender', 'female').draft.profileId).toBeNull();
    expect(editVoice(draft, { seed: 43 }).profileId).toBeNull();
    expect(editVoice(draft, { description: 'a deep voice' }).profileId).toBeNull();
  });

  it('stays linked when a value is set to what it already is', () => {
    const draft = restored();
    expect(pickDetail(draft, 'Gender', 'male').draft.profileId).toBe('designed-voice');
    expect(editVoice(draft, { seed: 42 }).profileId).toBe('designed-voice');
  });

  it('starts an unsaved design from a preset, personality or demo', () => {
    expect(replaceRecipe(restored(), { attrs: { Gender: 'female' } }).profileId).toBeNull();
  });

  it('does not send a profile the draft no longer matches (stale persisted drafts)', () => {
    const draft = restored();
    expect(linkedDesignProfile({ ...draft, seed: 7 }, [profile])).toBeNull();
    expect(
      linkedDesignProfile({ ...draft, attrs: { ...draft.attrs, Gender: 'female' } }, [profile]),
    ).toBeNull();
    expect(linkedDesignProfile(draft, [{ ...profile, kind: 'clone' }])).toBeNull();
    expect(linkedDesignProfile(draft, undefined)).toBeNull();
  });

  it('keeps a seedless saved voice seedless so it re-renders instead of redesigning', () => {
    const seedless = { ...profile, seed: null };
    const draft = { ...restored(), seed: 9 };
    expect(linkedDesignProfile(draft, [seedless])?.id).toBe('designed-voice');
    expect(designRequestSeed(draft, seedless)).toBeUndefined();
    expect(designRequestSeed(draft, profile)).toBe(9);
    expect(designRequestSeed(draft, null)).toBe(9);
  });
});

// CLEAN-ROOM (spec T1-folded §7): tests for designInstruct, free-form draft handling
// (applyDescription, pickDetail, designRecipe, designDraftFromTake, replaceRecipe,
// legacy-draft reading) go here.

describe('canResetToDescription', () => {
  const pick = { Age: { value: 'elderly', description: '' } };
  it('hides the reset while the description is empty, even with picks', () => {
    expect(canResetToDescription({ description: '  ', picks: pick, profileId: 'p' })).toBe(false);
  });
  it('hides the reset when the details already follow the description', () => {
    expect(canResetToDescription({ description: 'warm', picks: {}, profileId: null })).toBe(false);
  });
  it('offers the reset when picks or a saved voice override the description', () => {
    expect(canResetToDescription({ description: 'warm', picks: pick, profileId: null })).toBe(true);
    expect(canResetToDescription({ description: 'warm', picks: {}, profileId: 'p' })).toBe(true);
  });
});
