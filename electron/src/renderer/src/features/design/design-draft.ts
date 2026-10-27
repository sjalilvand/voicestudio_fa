import type { DesignRecipe, HistoryItem, InstructVocabulary, Profile } from '@/lib/api/types';
import { pickDesignSeed } from '@shared/utils/seed';
import {
  applyVdState,
  buildDesignInstruct,
  instructToVdStates,
  mergeDescribedAttrs,
} from '@shared/utils/voiceInstruct';
export const STORAGE = 'voicestudio.design.v1';
export const DESIGN_DRAFT_EVENT = 'voicestudio:design-draft';

/** A detail the user chose explicitly, and the description that was in effect then. */
export interface DesignPick {
  value: string;
  description: string;
}

export interface DesignDraft {
  text: string;
  /** Effective details: what the description maps to, with the picks on top. */
  attrs: Record<string, string>;
  seed: number;
  profileId: string | null;
  /** What the user wrote. */
  description: string;
  /** Explicit choices; each holds until the description says something else about it. */
  picks: Record<string, DesignPick>;
  // CLEAN-ROOM (spec W5-small §5.1): doc comment for `mapped`.
  mapped: Record<string, string>;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

// CLEAN-ROOM (spec W5-small §5.2): stringEntries helper.

/** Details that are set (not Auto), recorded as picks made under no description. */
function explicitPicks(attrs: Record<string, string>): Record<string, DesignPick> {
  const result: Record<string, DesignPick> = {};
  for (const category in attrs) {
    const value = attrs[category];
    if (value !== 'Auto') result[category] = { value, description: '' };
  }
  return result;
}

/** Strip a picks map down to category -> chosen value. */
function pickValues(picks: Record<string, DesignPick>): Record<string, string> {
  const values: Record<string, string> = {};
  for (const category in picks) values[category] = picks[category].value;
  return values;
}

function blankDraft(): DesignDraft {
  return {
    text: '',
    attrs: mergeDescribedAttrs(),
    seed: pickDesignSeed(false, null),
    profileId: null,
    description: '',
    picks: {},
    mapped: {},
  };
}

// CLEAN-ROOM (spec W5-small §5.3): readDraft().

export function writeDraft(draft: DesignDraft) {
  try {
    localStorage.setItem(STORAGE, JSON.stringify(draft));
  } catch {
    /* The mounted workspace can still receive the in-memory draft. */
  }
  window.dispatchEvent(new CustomEvent<DesignDraft>(DESIGN_DRAFT_EVENT, { detail: draft }));
}

// CLEAN-ROOM (spec W5-small §5.4): replaceRecipe().

/**
 * Change part of the voice (description, seed, details). The draft no longer
 * is the saved voice it came from, so it stops sending that voice: the
 * backend would otherwise keep cloning the saved sample and the edit would
 * barely be heard. Setting a value it already has changes nothing.
 */
export function editVoice(
  current: DesignDraft,
  patch: Partial<Pick<DesignDraft, 'attrs' | 'seed' | 'description' | 'picks'>>,
): DesignDraft {
  const changed = (Object.keys(patch) as (keyof typeof patch)[]).some(
    (key) => JSON.stringify(patch[key]) !== JSON.stringify(current[key]),
  );
  return changed ? { ...current, ...patch, profileId: null } : current;
}

function sameAttrs(left: Record<string, string>, right: Record<string, string>): boolean {
  return [...new Set([...Object.keys(left), ...Object.keys(right)])].every(
    (category) => (left[category] ?? 'Auto') === (right[category] ?? 'Auto'),
  );
}

/**
 * The saved design voice a take should re-render, or null. A draft links to
 * a design profile only while its details and seed are still the profile's,
 * so an edit made before linking was enforced (or restored from an older
 * draft) designs a new voice instead of cloning the saved sample.
 */
export function linkedDesignProfile(
  draft: Pick<DesignDraft, 'attrs' | 'seed' | 'profileId'>,
  profiles: readonly Profile[] | undefined,
): Profile | null {
  const profile = profiles?.find((item) => item.id === draft.profileId && item.kind === 'design');
  if (!profile) return null;
  const saved = restoreDesignProfile(profile, draft.seed);
  return saved.seed === draft.seed && sameAttrs(saved.attrs, draft.attrs) ? profile : null;
}

/**
 * The seed a take sends. A linked voice saved without a seed keeps its own
 * (none): the draft's placeholder would read as an edit and design a new
 * voice instead of re-rendering the saved one.
 */
export function designRequestSeed(
  draft: Pick<DesignDraft, 'seed'>,
  linked: Profile | null,
): number | undefined {
  return linked && linked.seed == null ? undefined : draft.seed;
}

// CLEAN-ROOM (spec W5-small §5.5): applyDescription().

/**
 * "Reset to description" drops the picks (and a saved-voice link) so the
 * description alone decides again. With no description there is nothing to
 * reset to, and without picks or a link the details already follow it.
 */
export function canResetToDescription(
  draft: Pick<DesignDraft, 'description' | 'picks' | 'profileId'>,
): boolean {
  return (
    draft.description.trim() !== '' &&
    (Object.keys(draft.picks).length > 0 || draft.profileId !== null)
  );
}

// CLEAN-ROOM (spec W5-small §5.6): pickDetail().

// CLEAN-ROOM (spec W5-small §5.7): designInstruct().

/** The part of the draft that is stored with the take. */
export function designRecipe(draft: Pick<DesignDraft, 'description' | 'picks'>): DesignRecipe {
  return { description: draft.description.trim(), picks: pickValues(draft.picks) };
}

interface StoredRecipe {
  description: string;
  picks: Record<string, string>;
  mapped: Record<string, string>;
}

function parseStoredRecipe(raw: string | null | undefined): StoredRecipe | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isPlainObject(parsed) || typeof parsed.description !== 'string') return null;
    return {
      description: parsed.description,
      picks: stringEntries(parsed.picks),
      mapped: stringEntries(parsed.mapped),
    };
  } catch {
    return null;
  }
}

// CLEAN-ROOM (spec W5-small §5.8): designDraftFromTake().

/** Restore a saved design recipe without leaking values from the previous voice. */
export function restoreDesignProfile(
  profile: Profile,
  fallbackSeed: number,
): Pick<DesignDraft, 'attrs' | 'seed' | 'profileId' | 'description' | 'picks' | 'mapped'> & {
  language: string;
} {
  const recipe = parseStoredRecipe(profile.design_recipe);
  const editedAttrs = instructToVdStates(profile.instruct ?? '');
  let attrs = editedAttrs;
  if (profile.vd_states) {
    try {
      const parsed = JSON.parse(profile.vd_states);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        // vd_states remains the source of truth for the effective category
        // controls, even if the free-form description covers richer traits.
        attrs = { ...editedAttrs, ...(parsed as Record<string, string>) };
      }
    } catch {
      /* The complete instruct-derived fallback remains usable. */
    }
  }
  const description = recipe?.description ?? '';
  const merged = mergeDescribedAttrs(attrs);
  return {
    attrs: merged,
    seed: profile.seed ?? fallbackSeed,
    profileId: profile.id,
    language: profile.language || 'Auto',
    description,
    mapped: recipe?.mapped ?? {},
    picks: recipe
      ? Object.fromEntries(
          Object.entries(recipe.picks).map(([category, value]) => [
            category,
            { value, description },
          ]),
        )
      : explicitPicks(merged),
  };
}
