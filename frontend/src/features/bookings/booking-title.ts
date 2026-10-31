/**
 * A booking title as a person reads it: "EC 111 · Warszawa → Praha · return · passengers 1–3".
 *
 * New titles already come from the backend in this shape; bookings created before it (stored
 * as "EC 111 Praha Warszawa -> Praha (return) (passengers 1-3) (rebooked)") are tidied here so
 * a room never mixes the two. "Rebooked" is not text — it is a badge (`replaces_booking_id`).
 */
export function bookingTitle(raw: string): string {
  return raw
    .replace(/\s*\(rebooked\)/gi, "")
    .replace(/\s*->\s*/g, " → ")
    .replace(/\s*\(passengers (\d+)-(\d+)\)/g, " · passengers $1–$2")
    .replace(/\s*\(([^()]+)\)/g, (_, inner: string) => ` · ${inner.split(/,\s*/).join(" · ")}`)
    .trim();
}
