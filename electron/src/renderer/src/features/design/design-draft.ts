import type { Profile } from '@/lib/api/types';
import { instructToVdStates, mergeDescribedAttrs } from '@shared/utils/voiceInstruct';
export const STORAGE = 'voicestudio.design.v1';
export const DESIGN_DRAFT_EVENT = 'voicestudio:design-draft';

// CLEAN-ROOM (spec T1-folded §7): the DesignDraft interface and DesignPick type go here.
// CLEAN-ROOM (spec T1-folded §7): readDraft() (with its record-parsing helpers) goes here.

export function writeDraft(draft: DesignDraft) {
  try {
    localStorage.setItem(STORAGE, JSON.stringify(draft));
  } catch {
    /* The mounted workspace can still receive the in-memory draft. */
  }
  window.dispatchEvent(new CustomEvent<DesignDraft>(DESIGN_DRAFT_EVENT, { detail: draft }));
}

// CLEAN-ROOM (spec T1-folded §7): replaceRecipe(current, recipe) goes here.

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

// CLEAN-ROOM (spec T1-folded §7): applyDescription(current, mapping, described) goes here.

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

// CLEAN-ROOM (spec T1-folded §7): pickDetail(), designInstruct(), designRecipe() and
// designDraftFromTake() (with its stored-recipe parser) go here.

/** Restore a saved design recipe without leaking values from the previous voice. */
export function restoreDesignProfile(
  profile: Profile,
  fallbackSeed: number,
): Pick<DesignDraft, 'attrs' | 'seed' | 'profileId' | 'description' | 'picks' | 'mapped'> & {
  language: string;
} {
  const recipe = parseRecipe(profile.design_recipe);
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
      : explicitDetails(merged),
  };
}
