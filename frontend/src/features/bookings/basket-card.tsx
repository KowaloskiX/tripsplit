import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { apiErrorMessage, type TripBookingsResponse } from "@/lib/api";

import { BatchRefusals } from "./batch-refusals";
import { CHANNEL_LABEL } from "./bookings-list";
import { formatMoney } from "./money";
import { useApproveAll } from "./mutations";

/**
 * Every purchase waiting for the organizer's approval, with the supplier's own total, and one
 * button that approves (= pays) them all. The server still refuses unless every share is paid.
 */
export function BasketCard({ trip }: { trip: TripBookingsResponse }): ReactNode {
  const approval = useApproveAll(trip.trip_id);
  const waiting = trip.bookings.filter((booking) => booking.status === "awaiting_approval");
  if (!trip.is_organizer || (waiting.length === 0 && !approval.data)) return null;
  const total = waiting.reduce((sum, booking) => sum + booking.amount_minor, 0);
  return (
    <Panel className="border-accent/60" role="region" aria-label="Approve the basket">
      <PanelHeader>
        <span className="text-accent">basket</span>
        <span>
          {waiting.length} purchase{waiting.length === 1 ? "" : "s"} awaiting approval
        </span>
      </PanelHeader>
      <div className="space-y-3 p-4">
        {waiting.length > 0 && (
          <ul className="divide-y divide-line">
            {waiting.map((booking) => (
              <li key={booking.id} className="flex items-baseline justify-between gap-3 py-2">
                <span className="min-w-0">
                  <span className="block truncate text-sm text-ink">{booking.title}</span>
                  <span className="ticket-mono text-xs text-muted">
                    {booking.supplier} · {CHANNEL_LABEL[booking.channel]}
                  </span>
                </span>
                <span className="ticket-mono shrink-0 text-sm text-ink">
                  {formatMoney(booking.amount_minor, trip.currency)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {approval.error && <ErrorCallout>{apiErrorMessage(approval.error)}</ErrorCallout>}
        {approval.data && <BatchRefusals items={approval.data.items} />}
        {waiting.length > 0 && (
          <Button
            className="w-full"
            disabled={approval.isPending}
            onClick={() => approval.approveAll()}
          >
            {approval.isPending
              ? "Approving…"
              : `Approve basket (total ${formatMoney(total, trip.currency)})`}
          </Button>
        )}
      </div>
    </Panel>
  );
}
