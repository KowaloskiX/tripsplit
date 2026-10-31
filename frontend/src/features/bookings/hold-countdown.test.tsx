import { describe, expect, it } from "vitest";

import { holdLeft } from "./hold-countdown";

const NOW = Date.parse("2026-11-01T12:00:00Z");

describe("holdLeft", () => {
  it("counts hours and minutes down to the minute", () => {
    expect(holdLeft("2026-11-02T11:14:30Z", NOW)).toBe("23h 14m left");
    expect(holdLeft("2026-11-01T12:09:59Z", NOW)).toBe("9m left");
  });

  it("says expired once the hold has lapsed", () => {
    expect(holdLeft("2026-11-01T12:00:00Z", NOW)).toBe("expired");
    expect(holdLeft("2026-10-31T12:00:00Z", NOW)).toBe("expired");
  });
});
