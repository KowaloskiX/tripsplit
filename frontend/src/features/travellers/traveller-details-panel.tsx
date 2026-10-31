import type { ReactNode } from "react";

import { Panel, PanelHeader } from "@/components/ui/panel";
import type { RoomResponse } from "@/lib/api";

import { detailsNeeded } from "./details-needed";
import { useMyTravellerDetails } from "./queries";
import { TravellerChecklist } from "./traveller-checklist";
import { TravellerDetailsForm } from "./traveller-details-form";

/** Everyone's completeness (no values) and the current user's own form. */
export function TravellerDetailsPanel({
  room,
  embedded = false,
}: {
  room: RoomResponse;
  /** Inside a section that already names it: no header of its own. */
  embedded?: boolean;
}): ReactNode {
  const mine = useMyTravellerDetails();
  const me = room.members.find((member) => member.user_id === room.my_user_id);
  const allComplete = room.members.every((member) => member.traveller_details_complete);
  return (
    <Panel role="region" aria-label="Traveller details">
      <PanelHeader className={embedded ? "sr-only" : undefined}>
        <span>Traveller details</span>
        <span className={allComplete ? "text-success" : "text-warn"}>
          {allComplete ? "everyone is ready" : "some details missing"}
        </span>
      </PanelHeader>
      <div className="space-y-4 p-4">
        <TravellerChecklist members={room.members} />
        {me && (
          <details
            open={detailsNeeded(room.trip.status, me.traveller_details_complete)}
            className="border-t border-line pt-3"
          >
            <summary className="cursor-pointer text-sm text-muted hover:text-ink">
              {me.traveller_details_complete ? "your travel details" : "Add your travel details"}
            </summary>
            <div className="pt-3">
              <TravellerDetailsForm tripId={room.trip.id} current={mine.data} />
            </div>
          </details>
        )}
      </div>
    </Panel>
  );
}
