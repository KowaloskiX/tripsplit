import { describe, expect, it } from "vitest";

import { callTone, formatCall } from "./model";

describe("formatCall", () => {
  it("prints a fixed-width terminal line", () => {
    expect(
      formatCall({
        at: "2026-11-20T12:04:31.512Z",
        method: "POST",
        path: "/air/orders",
        status: 201,
        ms: 412,
      }),
    ).toBe("12:04:31  POST   /air/orders  201  412ms");
  });
});

describe("callTone", () => {
  it("groups HTTP statuses", () => {
    expect(callTone(200)).toBe("ok");
    expect(callTone(201)).toBe("ok");
    expect(callTone(302)).toBe("redirect");
    expect(callTone(409)).toBe("client");
    expect(callTone(503)).toBe("server");
  });
});
