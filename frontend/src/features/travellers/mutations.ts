import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  travellerDetailsReadQueryKey,
  travellerDetailsUpdateMutation,
  tripsRoomQueryKey,
} from "@/lib/api";

import { type TravellerDetailsValues, toTravellerDetailsBody } from "./schema";

/** Saving refreshes the caller's details and the room's completeness badges. */
export function useUpdateTravellerDetails(tripId: string) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    ...travellerDetailsUpdateMutation(),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: travellerDetailsReadQueryKey() }),
        queryClient.invalidateQueries({
          queryKey: tripsRoomQueryKey({ path: { trip_id: tripId } }),
        }),
      ]);
    },
  });
  return {
    ...mutation,
    save: (values: TravellerDetailsValues): void =>
      mutation.mutate({ body: toTravellerDetailsBody(values) }),
  };
}
