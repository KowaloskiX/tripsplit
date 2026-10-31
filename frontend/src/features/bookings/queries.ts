import { useQuery } from "@tanstack/react-query";

import { agentRunsGraphOptions, agentRunsStatusOptions, bookingsListOptions } from "@/lib/api";

const LIST_POLL_MS = 2000;
const RUN_POLL_MS = 1000;
const inBrowser = typeof window !== "undefined";

/** The trip's bookings with their latest agent run. Polled: the agent moves them on its own. */
export function useTripBookings(tripId: string) {
  return useQuery({
    ...bookingsListOptions({ path: { trip_id: tripId } }),
    enabled: inBrowser,
    refetchInterval: LIST_POLL_MS,
  });
}

/** Live `status.json` of a run — polled every second only while the agent is working. */
export function useRunStatus(runId: string, active: boolean) {
  return useQuery({
    ...agentRunsStatusOptions({ path: { run_id: runId } }),
    enabled: inBrowser,
    refetchInterval: active ? RUN_POLL_MS : false,
  });
}

/**
 * The run's plan (`flow_graph.json`). It never changes once written, so it is polled only
 * until it exists (404 while the agent boots) and only while the run is active.
 */
export function useRunGraph(runId: string, active: boolean) {
  return useQuery({
    ...agentRunsGraphOptions({ path: { run_id: runId } }),
    enabled: inBrowser && runId !== "",
    retry: false,
    refetchInterval: (query) => (active && query.state.data === undefined ? RUN_POLL_MS : false),
  });
}
