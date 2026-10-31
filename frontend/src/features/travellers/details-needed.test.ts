import { describe, expect, it } from "vitest";

import { detailsNeeded } from "./details-needed";

describe("detailsNeeded", () => {
  it("keeps the form collapsed while the group is still choosing", () => {
    expect(detailsNeeded("collecting", false)).toBe(false);
    expect(detailsNeeded("voting", false)).toBe(false);
  });

  it("opens it once buying needs the details, and never for complete ones", () => {
    expect(detailsNeeded("paying", false)).toBe(true);
    expect(detailsNeeded("booking", false)).toBe(true);
    expect(detailsNeeded("booking", true)).toBe(false);
  });
});
