import { CreditCard, Landmark } from "lucide-react";
import type { ReactNode } from "react";

import type { BookingResponse } from "@/lib/api";

/** How the trip escrow paid (or will pay) a booking; null when there is nothing to say. */
export function paymentLabel(
  booking: Pick<BookingResponse, "status" | "payment_kind" | "card_last4">,
): string | null {
  const last4 = booking.card_last4 ?? "••••";
  if (booking.status === "confirmed") {
    if (booking.payment_kind === "virtual_card") return `Paid by virtual card •••• ${last4}`;
    if (booking.payment_kind === "payout") return "Paid to supplier (payout)";
    return null;
  }
  if (
    booking.payment_kind === "virtual_card" &&
    ["running", "awaiting_approval", "approved"].includes(booking.status)
  ) {
    return `Single-use card •••• ${last4} ready — funded when you approve`;
  }
  return null;
}

export function PaymentLine({ booking }: { booking: BookingResponse }): ReactNode {
  const label = paymentLabel(booking);
  if (label === null) return null;
  const Icon = booking.payment_kind === "payout" ? Landmark : CreditCard;
  return (
    <p className="mt-1 inline-flex items-center gap-1.5 text-xs text-muted">
      <Icon className="size-3.5" aria-hidden /> {label}
    </p>
  );
}
