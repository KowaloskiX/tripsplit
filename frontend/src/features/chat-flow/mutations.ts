import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  proposalsSelectMutation,
  tripsFeedQueryKey,
  tripsPostMessageMutation,
  tripsQuickCreateMutation,
  tripsRoomQueryKey,
} from "@/lib/api";

/** One sentence -> a trip, or the questions still to answer. */
export function useQuickBrief() {
  return useMutation(tripsQuickCreateMutation());
}

function useRefreshTrip(tripId: string): () => Promise<void> {
  const queryClient = useQueryClient();
  const path = { trip_id: tripId };
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: tripsRoomQueryKey({ path }) }),
      queryClient.invalidateQueries({ queryKey: tripsFeedQueryKey({ path }) }),
    ]);
  };
}

/** The picks become the trip's package; the vote closes and the shares open. */
export function useSelectOptions(tripId: string) {
  const onSuccess = useRefreshTrip(tripId);
  return useMutation({ ...proposalsSelectMutation(), onSuccess });
}

/** A line typed into the chat once the trip exists: everyone in the trip sees it. */
export function useSay(tripId: string) {
  const onSuccess = useRefreshTrip(tripId);
  return useMutation({ ...tripsPostMessageMutation(), onSuccess });
}
