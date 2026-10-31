import type { ReactNode } from "react";

import { ErrorCallout } from "@/components/ui/callout";
import { apiErrorMessage } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { BasketCard } from "./basket-card";
import { BookEverything } from "./book-everything";
import { BookingsList } from "./bookings-list";
import { DisruptionPanel } from "./disruption-panel";
import { useTripBookings } from "./queries";

const TRIP_STATUS_LABEL: Record<string, string> = {
  paying: "Waiting for everyone to pay",
  booking: "Booking",
  booked: "Everything booked",
  disrupted: "Disrupted",
  rebooking: "Rebooking",
  done: "Trip done",
};

/** The booking screen of a trip: what is being bought, the live agent, the approval. */
export function TripBookings({ tripId }: { tripId: string }): ReactNode {
  const query = useTripBookings(tripId);
  if (query.error) return <ErrorCallout>{apiErrorMessage(query.error)}</ErrorCallout>;
  if (!query.data) return <p className="text-sm text-muted">Loading bookings…</p>;
  const trip = query.data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="eyebrow">{TRIP_STATUS_LABEL[trip.trip_status] ?? trip.trip_status}</p>
        <p className="ticket-mono text-sm text-muted">
          total {formatMoney(trip.total_minor, trip.currency)}
        </p>
      </div>
      {trip.is_organizer && <BookEverything trip={trip} />}
      <BasketCard trip={trip} />
      <BookingsList trip={trip} travellers={trip.travellers} />
      <DisruptionPanel trip={trip} />
    </div>
  );
}
