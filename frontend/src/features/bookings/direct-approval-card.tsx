import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { apiErrorMessage, type BookingResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { HoldCountdown } from "./hold-countdown";
import { useApproveBooking } from "./mutations";

type DirectApprovalCardProps = {
  tripId: string;
  booking: BookingResponse;
  currency: string;
};

/** Approval of an API-channel purchase: no agent, no screenshot, the price is the supplier's quote. */
export function DirectApprovalCard({
  tripId,
  booking,
  currency,
}: DirectApprovalCardProps): ReactNode {
  const approval = useApproveBooking(tripId);
  const travellers = booking.passenger_user_ids.length;
  return (
    <Panel className="border-accent/60" role="region" aria-label="Approve the payment">
      <PanelHeader>
        <span className="text-accent">approval needed</span>
        <span>{booking.supplier} · direct</span>
      </PanelHeader>
      <div className="space-y-3 p-4">
        {approval.error && <ErrorCallout>{apiErrorMessage(approval.error)}</ErrorCallout>}
        <p className="font-mono text-2xl tracking-tight text-ink">
          {formatMoney(booking.amount_minor, currency)}
          {travellers > 0 && <span className="text-xs text-muted"> for {travellers} people</span>}
        </p>
        {booking.hold_expires_at && <HoldCountdown expiresAt={booking.hold_expires_at} />}
        <p className="text-sm text-muted">
          {booking.supplier} confirmed this price. Approving buys it through their booking API.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button disabled={approval.isPending} onClick={() => approval.decide(booking.id, true)}>
            Approve and pay
          </Button>
          <Button
            variant="outline"
            disabled={approval.isPending}
            onClick={() => approval.decide(booking.id, false)}
          >
            Reject
          </Button>
        </div>
      </div>
    </Panel>
  );
}
