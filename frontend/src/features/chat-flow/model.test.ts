import { describe, expect, it } from "vitest";

import type { EventResponse } from "@/lib/api";

import { groupMessages, legs, supplierTicks } from "./from-api";
import {
  answeredSteps,
  type ChatAction,
  type ChatState,
  chatReducer,
  INITIAL_CHAT,
  type Offered,
  pickingStep,
  tripPhase,
} from "./model";

const ALL: Offered = { transport: 3, stays: 4, activities: 2 };

function run(actions: ChatAction[], from: ChatState = INITIAL_CHAT): ChatState {
  return actions.reduce(chatReducer, from);
}

describe("picking steps", () => {
  it("walks transport -> stay -> activities -> summary", () => {
    expect(pickingStep(INITIAL_CHAT, ALL)).toBe("transport");
    const a = run([{ type: "pick_transport", id: "t1" }]);
    expect(pickingStep(a, ALL)).toBe("stay");
    const b = run([{ type: "pick_stay", id: "s0" }], a);
    expect(pickingStep(b, ALL)).toBe("activities");
    const c = run([{ type: "set_activities", ids: [] }], b);
    expect(pickingStep(c, ALL)).toBe("summary");
    expect(answeredSteps(c, ALL)).toEqual(["transport", "stay", "activities"]);
  });

  it("skips a kind the research found nothing of", () => {
    const state = run([{ type: "pick_transport", id: "t0" }]);
    expect(pickingStep(state, { transport: 2, stays: 0, activities: 0 })).toBe("summary");
    expect(answeredSteps(state, { transport: 2, stays: 0, activities: 0 })).toEqual(["transport"]);
  });

  it("reopens an earlier step with 'change' and keeps the later picks", () => {
    const done = run([
      { type: "pick_transport", id: "t0" },
      { type: "pick_stay", id: "s1" },
      { type: "set_activities", ids: ["a0"] },
    ]);
    const editing = run([{ type: "edit", step: "transport" }], done);
    expect(pickingStep(editing, ALL)).toBe("transport");
    // Nothing after the reopened step is shown as answered while it is open.
    expect(answeredSteps(editing, ALL)).toEqual([]);
    const changed = run([{ type: "pick_transport", id: "t2" }], editing);
    expect(changed.picks).toEqual({ transport: "t2", stay: "s1", activities: ["a0"] });
    expect(pickingStep(changed, ALL)).toBe("summary");
  });

  it("reopening the stay keeps the transport answered above it", () => {
    const done = run([
      { type: "pick_transport", id: "t0" },
      { type: "pick_stay", id: "s1" },
      { type: "set_activities", ids: [] },
      { type: "edit", step: "stay" },
    ]);
    expect(pickingStep(done, ALL)).toBe("stay");
    expect(answeredSteps(done, ALL)).toEqual(["transport"]);
  });

  it("resets", () => {
    expect(run([{ type: "pick_transport", id: "t0" }, { type: "reset" }])).toEqual(INITIAL_CHAT);
  });
});

describe("trip phase", () => {
  it("maps trip status and bookings onto the conversation", () => {
    expect(tripPhase({ status: "proposing", bookings: [] })).toBe("searching");
    expect(tripPhase({ status: "voting", bookings: [] })).toBe("picking");
    expect(tripPhase({ status: "paying", bookings: [] })).toBe("who");
    expect(tripPhase({ status: "booking", bookings: [{ status: "running" }] })).toBe("booking");
    expect(
      tripPhase({
        status: "booking",
        bookings: [{ status: "confirmed" }, { status: "awaiting_approval" }],
      }),
    ).toBe("approve");
    expect(tripPhase({ status: "booked", bookings: [] })).toBe("booked");
    expect(tripPhase({ status: "expired", bookings: [] })).toBe("stopped");
  });
});

function event(partial: Partial<EventResponse>): EventResponse {
  return {
    actor: "agent",
    actor_name: null,
    actor_user_id: null,
    created_at: "2026-11-01T10:00:00Z",
    id: Math.random().toString(36),
    kind: "message",
    message: "",
    payload: {},
    ...partial,
  };
}

describe("feed mapping", () => {
  it("ticks off the suppliers of the latest research only", () => {
    const progress = (supplier_id: string, kind: string, offers: number) =>
      event({
        payload: {
          supplier_progress: {
            supplier_id,
            supplier: supplier_id.toUpperCase(),
            kind,
            outcome: "ok",
            offers,
            seconds: 2.94,
          },
        },
      });
    const ticks = supplierTicks([
      event({ message: "Researching packages for 2 people" }),
      progress("pkp_intercity", "transport", 9),
      event({ message: "Researching packages for 2 people" }),
      progress("pkp_intercity", "transport", 4),
      progress("liteapi", "stay", 6),
      progress("duffel", "transport", 5),
    ]);
    expect(ticks.map((tick) => tick.line)).toEqual([
      "PKP_INTERCITY ✓ 4 trains · 2.9 s",
      "LITEAPI ✓ 6 stays · 2.9 s",
      "DUFFEL ✓ 5 flights · 2.9 s",
    ]);
  });

  it("shows the group's messages and, after the pick, its payments", () => {
    const messages = groupMessages(
      [
        event({ kind: "contribution_paid", message: "too early" }),
        event({ kind: "proposal_chosen", message: "Picked" }),
        event({
          kind: "member_joined",
          actor: "member",
          actor_name: "Kuba",
          message: "Kuba joined",
        }),
        event({
          kind: "message",
          actor: "member",
          actor_user_id: "me",
          actor_name: "Anna",
          message: "yay",
        }),
        event({ kind: "disruption", message: "Train delayed" }),
      ],
      "me",
    );
    expect(messages.map((m) => [m.text, m.mine, m.tone])).toEqual([
      ["Kuba joined", false, "info"],
      ["yay", true, "info"],
      ["Train delayed", false, "warn"],
    ]);
  });

  it("splits segments into out and back journeys with changes", () => {
    const segment = (number: string, departs: string, arrives: string) => ({
      carrier: "PKP Intercity",
      number: `IC ${number}`,
      origin: "A",
      destination: "B",
      departs_at: departs,
      arrives_at: arrives,
    });
    const journeys = legs([
      segment("1", "2026-11-20T06:00:00Z", "2026-11-20T09:00:00Z"),
      segment("2", "2026-11-20T09:30:00Z", "2026-11-20T11:00:00Z"),
      segment("3", "2026-11-22T17:00:00Z", "2026-11-22T22:15:00Z"),
    ]);
    expect(journeys.map((leg) => [leg.numbers, leg.duration, leg.changes])).toEqual([
      ["IC 1 + IC 2", "5h 00", 1],
      ["IC 3", "5h 15", 0],
    ]);
  });
});
