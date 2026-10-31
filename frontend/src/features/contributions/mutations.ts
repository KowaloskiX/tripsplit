import { useMutation, useQueryClient } from "@tanstack/react-query";

import { contributionsPayMutation, tripsFeedQueryKey, tripsRoomQueryKey } from "@/lib/api";

export function usePayShare(tripId: string) {
  const queryClient = useQueryClient();
  const path = { trip_id: tripId };
  return useMutation({
    ...contributionsPayMutation(),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: tripsRoomQueryKey({ path }) }),
        queryClient.invalidateQueries({ queryKey: tripsFeedQueryKey({ path }) }),
      ]);
    },
  });
}
