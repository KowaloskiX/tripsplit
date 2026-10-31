import { describe, expect, it } from "vitest";

import { amountError, blikCodeSchema, cardSchema, luhnValid, parseAmountMinor } from "./schema";

describe("wallet schema", () => {
  it("parses zł amounts into minor units", () => {
    expect(parseAmountMinor("250")).toBe(25_000);
    expect(parseAmountMinor("120,50")).toBe(12_050);
    expect(parseAmountMinor("1 000.5")).toBe(100_050);
    expect(parseAmountMinor("abc")).toBeNull();
    expect(amountError(50)).toBe("At least 1 zł.");
    expect(amountError(1_000_001)).toBe("At most 10 000 zł per top-up.");
    expect(amountError(25_000)).toBeUndefined();
  });

  it("accepts test cards by checksum and sends only what it must", () => {
    expect(luhnValid("4242424242424242")).toBe(true);
    expect(luhnValid("4242424242424241")).toBe(false);
    const now = new Date(2026, 9, 31);
    const ok = cardSchema(now).safeParse({
      number: "4242 4242 4242 4242",
      expiry: "12/28",
      cvc: "123",
    });
    expect(ok.success && ok.data.number.slice(-4)).toBe("4242");
    const expired = cardSchema(now).safeParse({
      number: "4242424242424242",
      expiry: "01/26",
      cvc: "123",
    });
    expect(expired.success).toBe(false);
  });

  it("wants six BLIK digits", () => {
    expect(blikCodeSchema.safeParse("123456").success).toBe(true);
    expect(blikCodeSchema.safeParse("12345").success).toBe(false);
  });
});
