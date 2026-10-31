import { useQuery } from "@tanstack/react-query";

import { tripsFeedOptions } from "@/lib/api";

export const FEED_POLL_MS = 2_000;

/**
 * The whole feed on every poll. A trip produces tens of events, not thousands, so a cursor
 * (`after`) would buy nothing but merge logic — the backend supports it for when it matters.
 */
export function useFeed(tripId: string) {
  return useQuery({
    ...tripsFeedOptions({ path: { trip_id: tripId } }),
    refetchInterval: FEED_POLL_MS,
    staleTime: 0,
  });
}
