import type { ReactNode } from "react";

import type { BatchItemResponse, BookingError } from "@/lib/api";

import { bookingTitle } from "./booking-title";

/** Why one booking of a batch did not go ahead, in a sentence for the organizer. */
export const REFUSAL_LABEL: Partial<Record<BookingError, string>> = {
  price_changed: "the price changed, so everyone tops up before booking again",
  trip_not_ready: "not everyone has paid their share yet",
  traveller_details_missing: "some travellers still need to add their details",
  sold_out: "the supplier no longer offers it",
  quote_expired: "the quote expired, start it again",
  supplier_unknown: "its supplier is not enabled",
  booking_not_startable: "it is already being bought",
  not_awaiting_approval: "it is no longer waiting for an approval",
};

/** The bookings a "book everything" / "approve the basket" click could not move. */
export function BatchRefusals({ items }: { items: readonly BatchItemResponse[] }): ReactNode {
  const refused = items.filter((item) => item.error !== null);
  if (refused.length === 0) return null;
  return (
    <ul className="space-y-1 text-sm text-warn" aria-label="Not done">
      {refused.map((item) => (
        <li key={item.booking.id}>
          {bookingTitle(item.booking.title)}:{" "}
          {item.error ? (REFUSAL_LABEL[item.error] ?? item.error) : ""}
        </li>
      ))}
    </ul>
  );
}
