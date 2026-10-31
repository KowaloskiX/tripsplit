import { BedDouble, Ticket, TrainFront } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Panel } from "@/components/ui/panel";
import {
  apiErrorMessage,
  type BookingKind,
  type BookingResponse,
  type BookingStatus,
  type TripBookingsResponse,
  type TripStatus,
} from "@/lib/api";

import { BookingStatusBadge } from "./booking-status-badge";
import { LiveAgentPanel } from "./live-agent-panel";
import { ManualCompletionForm } from "./manual-completion-form";
import { formatMoney } from "./money";
import { useStartBooking } from "./mutations";

/** Pastel fill per kind, matching the package cards: transport sky, stay lime, activity blush. */
const KIND_FILL: Record<BookingKind, string> = {
  train: "bg-pastel-sky",
  stay: "bg-pastel-lime",
  activity: "bg-pastel-blush",
};

const KIND_ICON: Record<BookingKind, typeof TrainFront> = {
  train: TrainFront,
  stay: BedDouble,
  activity: Ticket,
};

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
    return <p className="text-sm text-muted">Nothing to book yet — the group is still deciding.</p>;
  }
  return (
    <div className="space-y-4">
      {start.error && <ErrorCallout>{apiErrorMessage(start.error)}</ErrorCallout>}
      {trip.bookings.map((booking) => {
        const Icon = KIND_ICON[booking.kind];
        const showRun = booking.run !== null && booking.status !== "cancelled";
        return (
          <Panel key={booking.id} className={booking.status === "cancelled" ? "opacity-60" : ""}>
            <div className="flex flex-wrap items-center gap-3 px-4 py-4 sm:px-6">
              <span
                className={`inline-flex size-11 shrink-0 items-center justify-center rounded-2xl text-pastel-ink ${KIND_FILL[booking.kind]}`}
              >
                <Icon aria-label={booking.kind} className="size-5" />
              </span>
              <div className="min-w-[12rem] flex-1">
                <p className="text-base font-medium leading-snug tracking-[-0.01em] text-ink">
                  {booking.title}
                </p>
                <p className="ticket-mono mt-0.5 text-xs text-muted">
                  {booking.supplier} · {formatMoney(booking.amount_minor, trip.currency)}
                  {passengersLabel(booking)}
                </p>
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
            {canCompleteManually(trip, booking) && (
              <div className="border-t border-line px-4 pt-3">
                <ManualCompletionForm tripId={trip.trip_id} bookingId={booking.id} />
              </div>
            )}
            {showRun && (
              <div className="p-3 sm:p-4">
                <div aria-hidden className="perforation mb-3" />
                <LiveAgentPanel
                  tripId={trip.trip_id}
                  booking={booking}
                  currency={trip.currency}
                  isOrganizer={trip.is_organizer}
                  travellers={travellers}
                />
              </div>
            )}
          </Panel>
        );
      })}
    </div>
  );
}
