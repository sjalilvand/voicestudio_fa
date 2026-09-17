import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { toast } from 'sonner';
import { describeError } from '@/lib/api/client';
import {
  createCloneProfile,
  deleteProfile,
  listProfiles,
  type CreateCloneProfileInput,
} from '@/lib/api/profiles';
import type { Profile } from '@/lib/api/types';
import { tr } from '@/lib/i18n-text';
import { queryKeys } from '@/lib/query';
import { cloneSettingsStore, setCloneSetting } from '@/lib/store/clone-settings';
import { readDraft, writeDraft } from '@/features/design/design-draft';
import { useBackendStatus } from './use-backend-status';

const PROFILES_STALE_MS = 30_000;

export function useProfiles(): UseQueryResult<Profile[]> {
  const status = useBackendStatus();
  return useQuery({
    queryKey: queryKeys.profiles,
    queryFn: listProfiles,
    staleTime: PROFILES_STALE_MS,
    enabled: status.stage === 'ready',
  });
}

export function useCreateCloneProfile(): UseMutationResult<
  Profile,
  Error,
  CreateCloneProfileInput
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createCloneProfile,
    onSuccess: async (created) => {
      toast.success(tr('clone.saved_profile'));
      queryClient.setQueryData<Profile[]>(queryKeys.profiles, (old) => [
        created,
        ...(old ?? []).filter((p) => p.id !== created.id),
      ]);
      await queryClient.invalidateQueries({ queryKey: queryKeys.profiles });
    },
    onError: (err) => {
      toast.error(tr('clone.save_failed', { message: describeError(err) }));
    },
  });
}

export function useDeleteProfile(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteProfile,
    onSuccess: (_result, id) => {
      // The form must not keep pointing at a voice that no longer exists.
      if (cloneSettingsStore.state.selectedProfileId === id) {
        setCloneSetting('selectedProfileId', null);
      }
      const designDraft = readDraft();
      if (designDraft.profileId === id) {
        writeDraft({ ...designDraft, profileId: null });
      }
      toast.success(tr('clone.profile_deleted'));
      void queryClient.invalidateQueries({ queryKey: queryKeys.profiles });
    },
    onError: (err) => {
      toast.error(tr('clone.delete_profile_failed', { message: describeError(err) }));
    },
  });
}
