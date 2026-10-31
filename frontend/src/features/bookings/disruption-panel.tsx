import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { apiErrorMessage, type TripBookingsResponse } from "@/lib/api";

import { formatDelta, formatMoney } from "@/lib/money";
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
          <div className="space-y-2 text-sm">
            <p className="text-ink">
              Replaced {result.replacements.length}{" "}
              {result.replacements.length === 1 ? "purchase" : "purchases"}. Rebooking: new total{" "}
              {formatMoney(result.total_minor, trip.currency)} (
              {formatDelta(result.total_minor - result.previous_total_minor, trip.currency)}).
            </p>
            <ul className="divide-y divide-line text-sm tabular-nums">
              {result.shares.map((share) => (
                <li key={share.user_id} className="flex items-start justify-between gap-3 py-1.5">
                  <span className="min-w-0 truncate text-ink">{share.display_name}</span>
                  {/* Two short lines instead of one long one: no wrapping mid-amount at 390 px. */}
                  <span className="shrink-0 text-right">
                    <span className="block whitespace-nowrap text-ink">
                      {formatMoney(share.share_minor, trip.currency)}
                    </span>
                    <span className="block whitespace-nowrap text-xs text-muted">
                      {formatDelta(share.delta_minor, trip.currency)} · {share.status}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  );
}
