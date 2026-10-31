import { describe, expect, it } from "vitest";

import { formatDelta, formatMoney } from "./money";

describe("formatMoney", () => {
  it("groups thousands and keeps two decimals", () => {
    expect(formatMoney(124_000, "PLN")).toBe("1 240.00 PLN");
    expect(formatMoney(5, "PLN")).toBe("0.05 PLN");
    expect(formatMoney(123_456_789, "PLN")).toBe("1 234 567.89 PLN");
  });

  it("signs deltas", () => {
    expect(formatDelta(1_200, "PLN")).toBe("+12.00 PLN");
    expect(formatDelta(-1_200, "PLN")).toBe("-12.00 PLN");
  });
});

describe("one money format everywhere (QA finding 5)", () => {
  it("matches the backend feed messages, whatever the browser locale", () => {
    // core.domain.bookings.format_money(328_800, "PLN") == "3 288.00 PLN"
    expect(formatMoney(328_800)).toBe("3 288.00 PLN");
    expect(formatMoney(328_800, "EUR")).toBe("3 288.00 EUR");
  });
});
