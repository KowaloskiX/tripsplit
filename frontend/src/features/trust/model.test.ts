import { describe, expect, it } from "vitest";

import { checkedAgo, isExample, provenanceLabel } from "./model";

const NOW = Date.parse("2026-11-20T12:00:00Z");

describe("checkedAgo", () => {
  it("rounds to minutes, hours and days", () => {
    expect(checkedAgo("2026-11-20T11:59:40Z", NOW)).toBe("just now");
    expect(checkedAgo("2026-11-20T11:58:00Z", NOW)).toBe("2 min ago");
    expect(checkedAgo("2026-11-20T09:00:00Z", NOW)).toBe("3 h ago");
    expect(checkedAgo("2026-11-18T12:00:00Z", NOW)).toBe("2 d ago");
  });

  it("treats a bad timestamp as fresh rather than crashing", () => {
    expect(checkedAgo("not a date", NOW)).toBe("just now");
  });
});

describe("provenanceLabel", () => {
  it("names a live source with its freshness", () => {
    expect(
      provenanceLabel(
        { kind: "live", source: "PKP Intercity", checked_at: "2026-11-20T11:58:00Z" },
        NOW,
      ),
    ).toBe("Live from PKP Intercity · checked 2 min ago");
  });

  it("labels test and sandbox data as such", () => {
    expect(provenanceLabel({ kind: "test", source: "Duffel" })).toBe("Duffel test data");
    expect(provenanceLabel({ kind: "sandbox", source: "LiteAPI" })).toBe("LiteAPI sandbox");
  });

  it("never lends an example a real source", () => {
    expect(provenanceLabel({ kind: "example", source: "PKP Intercity" })).toBe(
      "Example · not bookable",
    );
    expect(isExample({ kind: "example" })).toBe(true);
    expect(isExample({ kind: "live" })).toBe(false);
    expect(isExample(null)).toBe(false);
  });
});
