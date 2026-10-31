import type { ReactNode } from "react";

import { MissionControl } from "./mission-control";
import type { MissionControlData } from "./model";

type BookingStageProps = {
  /** Live mission data; `null`/absent renders the booking UI exactly as before. */
  mission?: MissionControlData | null;
  /** The regular booking UI (cards, "Book everything", approvals) — always kept below. */
  children: ReactNode;
};

/** The room's booking stage: mission control on top once there is data to show. */
export function BookingStage({ mission, children }: BookingStageProps): ReactNode {
  if (!mission) return children;
  return (
    <div className="space-y-4">
      <MissionControl {...mission} />
      {children}
    </div>
  );
}
