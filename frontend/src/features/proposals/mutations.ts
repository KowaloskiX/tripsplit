import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  proposalsCloseVotingMutation,
  proposalsGenerateMutation,
  proposalsVoteMutation,
  tripsFeedQueryKey,
  tripsRoomQueryKey,
} from "@/lib/api";

/** Every package action changes the room and posts to the feed — refresh both at once. */
function useRefreshRoom(tripId: string): () => Promise<void> {
  const queryClient = useQueryClient();
  const path = { trip_id: tripId };
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: tripsRoomQueryKey({ path }) }),
      queryClient.invalidateQueries({ queryKey: tripsFeedQueryKey({ path }) }),
    ]);
  };
}

export function useGeneratePackages(tripId: string) {
  const onSuccess = useRefreshRoom(tripId);
  return useMutation({ ...proposalsGenerateMutation(), onSuccess });
}

export function useVote(tripId: string) {
  const onSuccess = useRefreshRoom(tripId);
  return useMutation({ ...proposalsVoteMutation(), onSuccess });
}

export function useCloseVoting(tripId: string) {
  const onSuccess = useRefreshRoom(tripId);
  return useMutation({ ...proposalsCloseVotingMutation(), onSuccess });
}
