import type { TripStatus } from "@/lib/api";

// From paying on, a purchase may wait for someone's details (e.g. a passport for a flight).
const BUYING: ReadonlySet<TripStatus> = new Set(["paying", "booking", "disrupted", "rebooking"]);

/**
 * Whether the user's own details form should be open: only when they are missing AND the trip
 * is at the stage that needs them. Earlier (collecting, voting) the form stays collapsed behind
 * "Add your travel details" so the stage card is not pushed off a phone screen.
 */
export function detailsNeeded(status: TripStatus, complete: boolean): boolean {
  return !complete && BUYING.has(status);
}
