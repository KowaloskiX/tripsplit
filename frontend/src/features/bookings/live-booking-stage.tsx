import type { ReactNode } from "react";

import { BookingStage } from "@/features/mission-control";

import { useMission } from "./mission";

type LiveBookingStageProps = { tripId: string; title: string; children: ReactNode };

/** The room's booking stage fed with live data: mission control while the trip is buying. */
export function LiveBookingStage({ tripId, title, children }: LiveBookingStageProps): ReactNode {
  const mission = useMission(tripId, title);
  return <BookingStage mission={mission}>{children}</BookingStage>;
}
