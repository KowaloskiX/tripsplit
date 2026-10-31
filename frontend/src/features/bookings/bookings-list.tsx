import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Disclosure } from "@/components/ui/disclosure";
import { Panel } from "@/components/ui/panel";
import { KIND_FILL, KindIcon } from "@/features/proposals";
import { OfferTrust } from "@/features/trust";
import {
  apiErrorMessage,
  type BookingResponse,
  type BookingStatus,
  type SupplierChannel,
  type TripBookingsResponse,
  type TripStatus,
} from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import { BookingStatusBadge } from "./booking-status-badge";
import {
  AgentWorkingBar,
  BookingTicket,
  isWorking,
  ReplacedStamp,
  StrikeLine,
} from "./booking-ticket";
import { bookingTitle } from "./booking-title";
import { DirectApprovalCard } from "./direct-approval-card";
import { HoldCountdown } from "./hold-countdown";
import { LiveAgentPanel } from "./live-agent-panel";
import { ManualCompletionForm } from "./manual-completion-form";
import { useStartBooking } from "./mutations";
import { PaymentLine } from "./payment-line";

/** How a purchase is made: the agent drives the site, the supplier's API, or a human. */
export const CHANNEL_LABEL: Record<SupplierChannel, string> = {
  agent: "agent",
  api: "direct",
  manual: "manual",
};
const LIVE_HOLD: ReadonlySet<BookingStatus> = new Set(["pending", "failed", "awaiting_approval"]);

// Mirrors the backend's rule; the server enforces it regardless of what the UI shows.
const TRIP_STATUSES_THAT_BUY: ReadonlySet<TripStatus> = new Set(["booking", "rebooking"]);
const STARTABLE: ReadonlySet<BookingStatus> = new Set(["pending", "failed", "handoff"]);
const COMPLETABLE_BY_HAND: ReadonlySet<BookingStatus> = new Set(["failed", "handoff"]);

export function canStart(trip: TripBookingsResponse, booking: BookingResponse): boolean {
  return (
    trip.is_organizer &&
    TRIP_STATUSES_THAT_BUY.has(trip.trip_status) &&
    STARTABLE.has(booking.status)
  );
}

export function canCompleteManually(trip: TripBookingsResponse, booking: BookingResponse): boolean {
  return (
    trip.is_organizer &&
    TRIP_STATUSES_THAT_BUY.has(trip.trip_status) &&
    COMPLETABLE_BY_HAND.has(booking.status)
  );
}

function passengersLabel(booking: BookingResponse): string {
  const count = booking.passenger_user_ids.length;
  return count > 0 ? ` · ${count} passenger${count === 1 ? "" : "s"}` : "";
}

export function BookingsList({
  trip,
  travellers,
}: {
  trip: TripBookingsResponse;
  travellers?: number | undefined;
}): ReactNode {
  const start = useStartBooking(trip.trip_id);
  if (trip.bookings.length === 0) {
    return <p className="text-sm text-muted">Nothing to book yet. The group is still deciding.</p>;
  }
  return (
    <div className="space-y-3">
      {start.error && <ErrorCallout>{apiErrorMessage(start.error)}</ErrorCallout>}
      {trip.bookings.map((booking) => {
        const showRun = booking.run !== null && booking.status !== "cancelled";
        const directApproval =
          trip.is_organizer && booking.channel === "api" && booking.status === "awaiting_approval";
        return (
          <Panel
            key={booking.id}
            className={cn(
              "relative",
              booking.status === "cancelled" && "opacity-60",
              booking.replaces_booking_id && booking.status !== "cancelled" && "slide-in-right",
            )}
          >
            <AgentWorkingBar active={isWorking(booking.status)} />
            <ReplacedStamp status={booking.status} />
            <div className="flex flex-wrap items-center gap-3 px-4 py-3.5 sm:px-5">
              <span
                className={cn(
                  "inline-flex size-9 shrink-0 items-center justify-center rounded-xl text-pastel-ink",
                  KIND_FILL[booking.kind],
                  isWorking(booking.status) && "halo",
                )}
              >
                <KindIcon kind={booking.kind} mode={booking.mode} className="size-4" />
              </span>
              <div className="min-w-0 flex-1 basis-40">
                <div className="flex min-w-0 items-start gap-2">
                  <p
                    title={bookingTitle(booking.title)}
                    className="relative line-clamp-1 min-w-0 break-words text-[15px] font-medium leading-snug text-ink"
                  >
                    {bookingTitle(booking.title)}
                    <StrikeLine active={booking.status === "cancelled"} />
                  </p>
                  {booking.replaces_booking_id && (
                    <Badge tone="info" className="mt-0.5 shrink-0">
                      rebooked
                    </Badge>
                  )}
                </div>
                <p className="mt-0.5 text-[13px] tabular-nums text-muted">
                  {booking.supplier} · {formatMoney(booking.amount_minor, trip.currency)}
                  {booking.status === "confirmed" && booking.confirmation_ref && (
                    <>
                      {" "}
                      · ref <span className="ticket-mono">{booking.confirmation_ref}</span>
                    </>
                  )}
                </p>
                {booking.hold_expires_at && LIVE_HOLD.has(booking.status) && (
                  <HoldCountdown expiresAt={booking.hold_expires_at} />
                )}
              </div>
              <BookingStatusBadge status={booking.status} />
              {canStart(trip, booking) && (
                <Button
                  size="sm"
                  disabled={start.isPending}
                  onClick={() => start.start(booking.id)}
                >
                  {booking.status === "pending" ? "Start booking" : "Try again"}
                </Button>
              )}
            </div>
            {directApproval && (
              <div className="border-t border-line p-3">
                <DirectApprovalCard
                  tripId={trip.trip_id}
                  booking={booking}
                  currency={trip.currency}
                />
              </div>
            )}
            {canCompleteManually(trip, booking) && (
              <div className="border-t border-line px-4 py-3 sm:px-5">
                <Disclosure summary="Finish it by hand">
                  <div className="pt-3">
                    <ManualCompletionForm tripId={trip.trip_id} bookingId={booking.id} />
                  </div>
                </Disclosure>
              </div>
            )}
            <div className="border-t border-line px-4 py-2.5 sm:px-5">
              {showRun ? (
                <LiveAgentPanel
                  tripId={trip.trip_id}
                  booking={booking}
                  currency={trip.currency}
                  isOrganizer={trip.is_organizer}
                  travellers={travellers}
                >
                  <BookingExtras booking={booking} currency={trip.currency} />
                </LiveAgentPanel>
              ) : (
                <Disclosure summary="Details">
                  <BookingExtras booking={booking} currency={trip.currency} />
                </Disclosure>
              )}
            </div>
          </Panel>
        );
      })}
    </div>
  );
}

/** What only matters on a closer look: how it is paid, links and photos, the ticket. */
function BookingExtras({
  booking,
  currency,
}: {
  booking: BookingResponse;
  currency: string;
}): ReactNode {
  return (
    <div className="space-y-3 pt-3 pb-1">
      <p className="text-xs text-muted">
        Bought{" "}
        {CHANNEL_LABEL[booking.channel] === "agent"
          ? "by the agent"
          : CHANNEL_LABEL[booking.channel]}
        {passengersLabel(booking)}
      </p>
      <PaymentLine booking={booking} />
      <OfferTrust
        links={booking.links}
        images={booking.images}
        provenance={booking.provenance}
        title={booking.title}
        photos={booking.kind === "stay"}
      />
      <BookingTicket booking={booking} currency={currency} />
    </div>
  );
}
