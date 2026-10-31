import { describe, expect, it } from "vitest";

import { bookingTitle } from "./booking-title";

describe("bookingTitle", () => {
  it("turns a legacy machine-built title into the readable one", () => {
    expect(
      bookingTitle("EC 111 Praha Warszawa -> Praha (return) (passengers 1-3) (rebooked)"),
    ).toBe("EC 111 Praha Warszawa → Praha · return · passengers 1–3");
    expect(bookingTitle("PKP Intercity EC 131 A -> B (2. class, return)")).toBe(
      "PKP Intercity EC 131 A → B · 2. class · return",
    );
  });

  it("leaves a new-style title alone", () => {
    const title = "EC 111 Praha · Warszawa → Praha · return · passengers 1–3";
    expect(bookingTitle(title)).toBe(title);
  });
});
