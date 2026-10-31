import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { apiErrorMessage, type RoomResponse, type TripStatus } from "@/lib/api";

import { useLeaveTrip } from "./mutations";

// Mirrors the backend: leaving is possible until the agent starts buying. The server also
// refuses once any booking has started — its error is shown as is.
const LEAVABLE: ReadonlySet<TripStatus> = new Set(["collecting", "proposing", "voting", "paying"]);

/** A member drops out. Two clicks: the first one only asks. */
export function LeaveTripButton({ room }: { room: RoomResponse }): ReactNode {
  const [confirming, setConfirming] = useState(false);
  const leave = useLeaveTrip(room.trip.id);
  if (room.my_role === "organizer" || !LEAVABLE.has(room.trip.status)) return null;
  const paid = (room.my_contribution?.paid_minor ?? 0) > 0;

  return (
    <div className="space-y-2">
      {leave.error && <ErrorCallout>{apiErrorMessage(leave.error)}</ErrorCallout>}
      {confirming ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted">
            {paid
              ? "Leave? Your payment will be refunded and the rest re-split the cost."
              : "Leave? The rest of the group re-split the cost."}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={leave.isPending}
            onClick={() => void leave.leave()}
          >
            {leave.isPending ? "Leaving…" : "Yes, leave"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
            Stay
          </Button>
        </div>
      ) : (
        <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>
          Leave trip
        </Button>
      )}
    </div>
  );
}
