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
        <span>shares</span>
        <span>{formatMoney(trip.total_minor, trip.currency)} total</span>
      </PanelHeader>
      <div className="space-y-4 p-4">
        {pay.error && <ErrorCallout>{apiErrorMessage(pay.error)}</ErrorCallout>}
        {canPay && (
          <Button
            className="w-full"
            onClick={() => pay.mutate({ path: { trip_id: trip.id } })}
            disabled={pay.isPending}
          >
            {pay.isPending
              ? "Paying…"
              : `Pay my share · ${formatMoney(mine.outstanding_minor, trip.currency)}`}
          </Button>
        )}
        {trip.status === "paying" && !canPay && (
          <p className="text-sm text-muted">
            Your share is paid. The agent books as soon as everyone else has paid too.
          </p>
        )}
        {trip.status === "booking" && (
          <p className="text-sm text-live">
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
