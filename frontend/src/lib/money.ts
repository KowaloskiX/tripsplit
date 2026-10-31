/**
 * `124000, "PLN"` -> `"1 240.00 PLN"` — THE money format of the app: every screen and every
 * backend feed message (`core.domain.bookings.format_money`) write amounts this one way.
 */
export function formatMoney(amountMinor: number, currency = "PLN"): string {
  const sign = amountMinor < 0 ? "-" : "";
  const absolute = Math.abs(amountMinor);
  const whole = Math.floor(absolute / 100)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const grosze = (absolute % 100).toString().padStart(2, "0");
  return `${sign}${whole}.${grosze} ${currency}`;
}

/** `1200` -> `"+12.00 PLN"`. */
export function formatDelta(amountMinor: number, currency: string): string {
  return `${amountMinor >= 0 ? "+" : ""}${formatMoney(amountMinor, currency)}`;
}
