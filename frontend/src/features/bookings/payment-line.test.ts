import { describe, expect, it } from "vitest";

import { paymentLabel } from "./payment-line";

describe("paymentLabel", () => {
  it("names the virtual card once the purchase is confirmed", () => {
    expect(
      paymentLabel({ status: "confirmed", payment_kind: "virtual_card", card_last4: "4242" }),
    ).toBe("Paid by virtual card •••• 4242");
  });

  it("says a payout went to an API supplier", () => {
    expect(paymentLabel({ status: "confirmed", payment_kind: "payout", card_last4: null })).toBe(
      "Paid to supplier (payout)",
    );
  });

  it("announces the card while the agent works, and nothing for unpaid bookings", () => {
    expect(
      paymentLabel({
        status: "awaiting_approval",
        payment_kind: "virtual_card",
        card_last4: "4242",
      }),
    ).toContain("funded when you approve");
    expect(paymentLabel({ status: "pending", payment_kind: null, card_last4: null })).toBeNull();
  });
});
