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
