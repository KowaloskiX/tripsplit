import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { apiErrorMessage, type TripBookingsResponse } from "@/lib/api";

import { DisruptionAlert } from "./disruption-alert";
import { useSimulateDisruption } from "./mutations";

// Mirrors the backend: a confirmed booking on a trip that is booked, or still booking the rest.
function canDisrupt(trip: TripBookingsResponse): boolean {
  const live = trip.trip_status === "booked" || trip.trip_status === "booking";
  return live && trip.bookings.some((booking) => booking.status === "confirmed");
}

/**
 * Dev-only demo trigger: "the train is delayed" -> rebooking + re-split. The endpoint itself
 * answers 404 outside dev/test; hiding the button is only cosmetics.
 */
export function DisruptionPanel({ trip }: { trip: TripBookingsResponse }): ReactNode {
  const disruption = useSimulateDisruption(trip.trip_id);
  const result = disruption.data;
  if (!import.meta.env.DEV || !trip.is_organizer) return null;
  if (!canDisrupt(trip) && !result) return null;

  return (
    <Panel>
      <PanelHeader>
        <span>Demo · disruption</span>
        <span>dev only</span>
      </PanelHeader>
      <div className="space-y-3 p-4">
        {!result && (
          <Button variant="outline" disabled={disruption.isPending} onClick={disruption.disrupt}>
            Simulate disruption
          </Button>
        )}
        {disruption.error && <ErrorCallout>{apiErrorMessage(disruption.error)}</ErrorCallout>}
        {result && (
          <DisruptionAlert
            replacements={result.replacements.length}
            totalMinor={result.total_minor}
            previousTotalMinor={result.previous_total_minor}
            shares={result.shares}
            currency={trip.currency}
          />
        )}
      </div>
    </Panel>
  );
}
