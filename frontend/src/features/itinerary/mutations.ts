import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  attractionsListQueryKey,
  attractionsVoteMutation,
  bookingsListQueryKey,
  itineraryGenerateMutation,
  itineraryGetQueryKey,
  tripsFeedQueryKey,
  tripsRoomQueryKey,
} from "@/lib/api";

/** A vote or a new plan changes the list, the plan, the feed — and tickets change the shares. */
function useRefresh(tripId: string): () => Promise<void> {
  const queryClient = useQueryClient();
  const path = { trip_id: tripId };
  return async () => {
    await Promise.all(
      [
        attractionsListQueryKey({ path }),
        itineraryGetQueryKey({ path }),
        tripsFeedQueryKey({ path }),
        tripsRoomQueryKey({ path }),
        bookingsListQueryKey({ path }),
      ].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    );
  };
}

export function useToggleAttractionVote(tripId: string) {
  const onSuccess = useRefresh(tripId);
  return useMutation({ ...attractionsVoteMutation(), onSuccess });
}

export function useGenerateItinerary(tripId: string) {
  const onSuccess = useRefresh(tripId);
  return useMutation({ ...itineraryGenerateMutation(), onSuccess });
}
