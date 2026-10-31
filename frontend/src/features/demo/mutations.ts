import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  demoPayAllMutation,
  demoSeedMembersMutation,
  demoVoteAllMutation,
  tripsFeedQueryKey,
  tripsRoomQueryKey,
} from "@/lib/api";

function useRefresh(tripId: string): () => Promise<void> {
  const queryClient = useQueryClient();
  const path = { trip_id: tripId };
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: tripsRoomQueryKey({ path }) }),
      queryClient.invalidateQueries({ queryKey: tripsFeedQueryKey({ path }) }),
    ]);
  };
}

export function useSeedMembers(tripId: string) {
  return useMutation({ ...demoSeedMembersMutation(), onSuccess: useRefresh(tripId) });
}

export function useVoteAll(tripId: string) {
  return useMutation({ ...demoVoteAllMutation(), onSuccess: useRefresh(tripId) });
}

export function usePayAll(tripId: string) {
  return useMutation({ ...demoPayAllMutation(), onSuccess: useRefresh(tripId) });
}
