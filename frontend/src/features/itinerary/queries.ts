import { useQuery } from "@tanstack/react-query";

import { attractionsListOptions, itineraryGetOptions } from "@/lib/api";

/** Other members vote too: poll gently while the panel is on screen. */
const POLL_MS = 4000;

export function useAttractions(tripId: string, enabled: boolean) {
  return useQuery({
    ...attractionsListOptions({ path: { trip_id: tripId } }),
    enabled,
    refetchInterval: POLL_MS,
  });
}

export function useItinerary(tripId: string, enabled: boolean) {
  return useQuery({
    ...itineraryGetOptions({ path: { trip_id: tripId } }),
    enabled,
    refetchInterval: POLL_MS,
  });
}
