import { useMutation, useQueryClient } from "@tanstack/react-query";

import { tripsFeedQueryKey, tripsPostMessageMutation } from "@/lib/api";

export function usePostMessage(tripId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    ...tripsPostMessageMutation(),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: tripsFeedQueryKey({ path: { trip_id: tripId } }) }),
  });
}
