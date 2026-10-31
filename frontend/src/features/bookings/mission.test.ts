import { describe, expect, it } from "vitest";

import type { BookingResponse } from "@/lib/api";

import { activeAgentBooking, apiCalls, graphSteps, stayMission } from "./mission";

function booking(overrides: Partial<BookingResponse>): BookingResponse {
  return {
    id: "b1",
    trip_id: "t1",
    kind: "transport",
    mode: "rail",
    title: "EC 131",
    supplier: "Demo rail",
    supplier_url: "http://localhost:8000/api/demo-supplier/rail",
    supplier_id: "demo_rail",
    channel: "agent",
    hold_expires_at: null,
    amount_minor: 100_00,
    passenger_user_ids: [],
    run: null,
    status: "pending",
    confirmation_ref: null,
    replaces_booking_id: null,
    links: [],
    images: [],
    provenance: null,
    ...overrides,
  };
}

const RUN = {
  run_id: "r1",
  status: "running" as const,
  steps: 3,
  cost_usd: 0,
  milestone: null,
  outcome: null,
  reason: "",
  started_at: null,
  finished_at: null,
};

describe("mission mapping", () => {
  it("prefers the agent run that is working over a finished one", () => {
    const done = booking({ id: "a", status: "confirmed", run: { ...RUN, run_id: "old" } });
    const working = booking({ id: "b", status: "running", run: RUN });
    expect(activeAgentBooking([done, working])?.id).toBe("b");
    expect(activeAgentBooking([done])?.id).toBe("a");
  });

  it("keeps graph step ids unique when an index repeats", () => {
    const step = {
      index: 1,
      kind: "click",
      node_id: null,
      source: "flow" as const,
      status: "done" as const,
      duration_ms: null,
      iteration: null,
    };
    const ids = graphSteps([step, step]).map((s) => s.id);
    expect(new Set(ids).size).toBe(2);
    expect(graphSteps([step])[0]?.label).toBe("click");
  });

  it("prints an unanswered call with status 0 and an unknown method as GET", () => {
    const [call] = apiCalls([
      {
        at: "2026-11-20T10:00:00Z",
        method: "HEAD",
        path: "/x",
        status: null,
        ms: 5,
        supplier: "Duffel",
        supplier_id: "duffel",
      },
    ]);
    expect(call).toMatchObject({ method: "GET", status: 0, supplier: "Duffel" });
  });

  it("walks the stay through prebook and book", () => {
    const waiting = stayMission(booking({ kind: "stay", status: "awaiting_approval" }));
    expect(waiting.steps.map((s) => s.state)).toEqual(["done", "done", "pending"]);
    const booked = stayMission(
      booking({ kind: "stay", status: "confirmed", confirmation_ref: "LITE-1" }),
    );
    expect(booked.steps.at(-1)).toMatchObject({ state: "done", detail: "LITE-1" });
  });
});
