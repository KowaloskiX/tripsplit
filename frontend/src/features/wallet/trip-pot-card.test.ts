import { describe, expect, it } from "vitest";

import { payByLeft } from "./trip-pot-card";

describe("payByLeft", () => {
  const now = Date.parse("2026-11-01T12:00:00Z");

  it("counts days, hours and minutes down to the deadline", () => {
    expect(payByLeft("2026-11-02T16:30:00Z", now)).toBe("1 d 4 h left");
    expect(payByLeft("2026-11-01T14:05:00Z", now)).toBe("2 h 5 min left");
    expect(payByLeft("2026-11-01T12:00:30Z", now)).toBe("1 min left");
  });

  it("says when it has passed", () => {
    expect(payByLeft("2026-11-01T11:00:00Z", now)).toBe("deadline passed");
  });
});
