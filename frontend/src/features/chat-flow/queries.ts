import { useQuery } from "@tanstack/react-query";

import { proposalsOptionsOptions, tripsFeedOptions } from "@/lib/api";

/**
 * What the research found, to pick from. Fetched once the trip is VOTING; the server answers
 * 409 while it still researches, so a failure is retried a few times rather than shown.
 */
export function useTripOptions(tripId: string, enabled: boolean) {
  return useQuery({
    ...proposalsOptionsOptions({ path: { trip_id: tripId } }),
    enabled: enabled && typeof window !== "undefined",
    retry: 3,
    staleTime: 60_000,
  });
}

/** The trip feed — supplier ticks while researching, the friends afterwards. Polled. */
export function useTripFeed(tripId: string) {
  return useQuery({
    ...tripsFeedOptions({ path: { trip_id: tripId } }),
    enabled: typeof window !== "undefined",
    refetchInterval: 1_500,
    staleTime: 0,
  });
}
