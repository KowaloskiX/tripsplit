import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { PayShareSheet, useOpenPayShare } from "@/features/wallet";
import type { RoomResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";

import { ContributionsTable } from "./contributions-table";

export function ContributionsPanel({ room }: { room: RoomResponse }): ReactNode {
  const { trip, my_contribution: mine } = room;
  const openPayShare = useOpenPayShare();
  if (room.contributions.length === 0) return null;
  const canPay = trip.status === "paying" && mine !== null && mine.outstanding_minor > 0;

  return (
    <Panel>
      <PanelHeader>
        <span>Shares</span>
        <span>{formatMoney(trip.total_minor, trip.currency)} total</span>
      </PanelHeader>
      <div className="space-y-4 p-4 sm:p-5">
        {canPay && (
          <Button
            size="lg"
            className="w-full"
            onClick={() => openPayShare(trip.id, mine.outstanding_minor)}
          >
            Pay my share · {formatMoney(mine.outstanding_minor, trip.currency)}
          </Button>
        )}
        <PayShareSheet tripId={trip.id} currency={trip.currency} />
        {mine !== null && mine.refund_minor > 0 && (
          <p className="rounded-[var(--radius-control)] bg-info-soft px-3.5 py-2.5 text-sm text-info">
            You get {formatMoney(mine.refund_minor, trip.currency)} back. You paid more than your
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
            Everyone paid. The organizer can start the bookings above.
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
