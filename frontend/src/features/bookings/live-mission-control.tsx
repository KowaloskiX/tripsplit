import type { ReactNode } from "react";

import { MissionControl } from "@/features/mission-control";

import { useMission } from "./mission";

/** Mission control fed with live data while the trip is buying; nothing otherwise. */
export function LiveMissionControl({
  tripId,
  title,
}: {
  tripId: string;
  title: string;
}): ReactNode {
  const mission = useMission(tripId, title);
  return mission ? <MissionControl {...mission} /> : null;
}
