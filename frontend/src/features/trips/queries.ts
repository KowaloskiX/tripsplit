import { useQuery } from "@tanstack/react-query";

import { tripsListOptions, tripsRoomOptions } from "@/lib/api";

/** The room changes under everyone's feet (votes, payments, the agent) — hence polling. */
export const ROOM_POLL_MS = 2_000;

export function useMyTrips() {
  return useQuery(tripsListOptions());
}

export function useRoom(tripId: string) {
  return useQuery({
    ...tripsRoomOptions({ path: { trip_id: tripId } }),
    refetchInterval: ROOM_POLL_MS,
    staleTime: 0,
  });
}
