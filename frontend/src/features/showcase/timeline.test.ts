import { describe, expect, it } from "vitest";

import { cueIndex } from "./timeline";

describe("cueIndex", () => {
  const cues = [0, 500, 1200];

  it("counts the cues already passed", () => {
    expect(cueIndex(cues, 0)).toBe(1);
    expect(cueIndex(cues, 499)).toBe(1);
    expect(cueIndex(cues, 500)).toBe(2);
    expect(cueIndex(cues, 5000)).toBe(3);
  });

  it("is zero before the first cue", () => {
    expect(cueIndex([100], 50)).toBe(0);
  });
});
