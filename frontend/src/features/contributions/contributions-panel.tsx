import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { apiErrorMessage, type RoomResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";

import { ContributionsTable } from "./contributions-table";
import { usePayShare } from "./mutations";

export function ContributionsPanel({ room }: { room: RoomResponse }): ReactNode {
  const { trip, my_contribution: mine } = room;
  const pay = usePayShare(trip.id);
  if (room.contributions.length === 0) return null;
  const canPay = trip.status === "paying" && mine !== null && mine.outstanding_minor > 0;

  return (
    <Panel>
      <PanelHeader>
        <span>Shares</span>
        <span>{formatMoney(trip.total_minor, trip.currency)} total</span>
      </PanelHeader>
      <div className="space-y-4 p-4 sm:p-5">
        {pay.error && <ErrorCallout>{apiErrorMessage(pay.error)}</ErrorCallout>}
        {canPay && (
          <Button
            size="lg"
            className="w-full"
            onClick={() => pay.mutate({ path: { trip_id: trip.id } })}
            disabled={pay.isPending}
          >
            {pay.isPending
              ? "Paying…"
              : `Pay my share · ${formatMoney(mine.outstanding_minor, trip.currency)}`}
          </Button>
        )}
        {mine !== null && mine.refund_minor > 0 && (
          <p className="rounded-[var(--radius-control)] bg-info-soft px-3.5 py-2.5 text-sm text-info">
            You get {formatMoney(mine.refund_minor, trip.currency)} back — you paid more than your
            current share.
          </p>
        )}
        {trip.status === "paying" && !canPay && (mine === null || mine.refund_minor === 0) && (
          <p className="text-sm text-muted">
            Your share is paid. The agent books as soon as everyone else has paid too.
          </p>
        )}
        {trip.status === "booking" && (
          <p className="rounded-[var(--radius-control)] bg-success-soft px-3.5 py-2.5 text-sm text-success">
            Everyone paid — the organizer can start the bookings above.
          </p>
        )}
        <ContributionsTable
          contributions={room.contributions}
          currency={trip.currency}
          myUserId={room.my_user_id}
        />
      </div>
    </Panel>
  );
}
