import type { ReactNode } from "react";

import { Panel, PanelHeader } from "@/components/ui/panel";
import type { RoomResponse } from "@/lib/api";

import { useMyTravellerDetails } from "./queries";
import { TravellerChecklist } from "./traveller-checklist";
import { TravellerDetailsForm } from "./traveller-details-form";

/** Everyone's completeness (no values) and the current user's own form. */
export function TravellerDetailsPanel({ room }: { room: RoomResponse }): ReactNode {
  const mine = useMyTravellerDetails();
  const me = room.members.find((member) => member.user_id === room.my_user_id);
  const allComplete = room.members.every((member) => member.traveller_details_complete);
  return (
    <Panel role="region" aria-label="Traveller details">
      <PanelHeader>
        <span>traveller details</span>
        <span className={allComplete ? "text-live" : "text-danger"}>
          {allComplete ? "everyone is ready" : "some details missing"}
        </span>
      </PanelHeader>
      <div className="space-y-4 p-4">
        <TravellerChecklist members={room.members} />
        {me && (
          <details open={!me.traveller_details_complete} className="border-t border-line pt-3">
            <summary className="cursor-pointer font-mono text-xs text-muted">your details</summary>
            <div className="pt-3">
              <TravellerDetailsForm tripId={room.trip.id} current={mine.data} />
            </div>
          </details>
        )}
      </div>
    </Panel>
  );
}
