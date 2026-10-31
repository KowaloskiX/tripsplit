/**
 * The chat flow's state machine — pure, so every step transition is unit-tested.
 *
 * Two halves: what the SERVER says (the trip's phase, from its status, shares and bookings)
 * and what the organizer picked locally before the package exists (transport, stay,
 * activities). Together they decide which step of the conversation is active.
 */
import type { BookingStatus, TripStatus } from "@/lib/api";

export type PickStep = "transport" | "stay" | "activities";

export type Picks = {
  transport: string | null;
  stay: string | null;
  /** null = not answered yet; [] = skipped. */
  activities: readonly string[] | null;
};

export type ChatState = {
  picks: Picks;
  /** A step the organizer reopened with "change"; null = going forward. */
  editing: PickStep | null;
};

export const INITIAL_CHAT: ChatState = {
  picks: { transport: null, stay: null, activities: null },
  editing: null,
};

export type ChatAction =
  | { type: "pick_transport"; id: string }
  | { type: "pick_stay"; id: string }
  | { type: "set_activities"; ids: readonly string[] }
  | { type: "edit"; step: PickStep }
  | { type: "reset" };

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "pick_transport":
      return { picks: { ...state.picks, transport: action.id }, editing: null };
    case "pick_stay":
      return { picks: { ...state.picks, stay: action.id }, editing: null };
    case "set_activities":
      return { picks: { ...state.picks, activities: [...action.ids] }, editing: null };
    case "edit":
      return { ...state, editing: action.step };
    case "reset":
      return INITIAL_CHAT;
  }
}

/** What the research offered, as counts: a kind with nothing is skipped. */
export type Offered = { transport: number; stays: number; activities: number };

export type PickingStep = PickStep | "summary";

/** The active step while picking: the reopened one, else the first unanswered one. */
export function pickingStep(state: ChatState, offered: Offered): PickingStep {
  if (state.editing) return state.editing;
  const { picks } = state;
  if (picks.transport === null) return "transport";
  if (offered.stays > 0 && picks.stay === null) return "stay";
  if (offered.activities > 0 && picks.activities === null) return "activities";
  return "summary";
}

/** The steps already answered, in conversation order (each shows the user's choice). */
export function answeredSteps(state: ChatState, offered: Offered): PickStep[] {
  const active = pickingStep(state, offered);
  const order: PickStep[] = ["transport", "stay", "activities"];
  const answered = order.filter((step) => {
    if (step === "transport") return state.picks.transport !== null;
    if (step === "stay") return offered.stays > 0 && state.picks.stay !== null;
    return offered.activities > 0 && state.picks.activities !== null;
  });
  if (active === "summary") return answered;
  // Everything before the active step stays visible; the active one is asked again below.
  const cut = order.indexOf(active);
  return answered.filter((step) => order.indexOf(step) < cut);
}

/** Where the trip is, server-side, as the chat sees it. */
export type TripPhase =
  | "searching" // the research runs
  | "picking" // options are in; nothing chosen yet
  | "who" // a package is chosen; shares open, someone has to pay
  | "booking" // everyone paid; the agent buys
  | "approve" // purchases wait for the organizer's approval
  | "booked" // tickets
  | "stopped"; // expired or failed: the room explains

export type PhaseInput = {
  status: TripStatus;
  bookings: readonly { status: BookingStatus }[];
};

const BOOKING_STATUSES: ReadonlySet<TripStatus> = new Set(["booking", "disrupted", "rebooking"]);

export function tripPhase({ status, bookings }: PhaseInput): TripPhase {
  if (status === "collecting" || status === "proposing") return "searching";
  if (status === "voting") return "picking";
  if (status === "paying") return "who";
  if (status === "booked" || status === "done") return "booked";
  if (BOOKING_STATUSES.has(status)) {
    return bookings.some((booking) => booking.status === "awaiting_approval")
      ? "approve"
      : "booking";
  }
  return "stopped";
}

/** The steps of the whole flow, for a compact progress line at the top. */
export const FLOW_STEPS = ["Brief", "Search", "Pick", "Pay", "Book"] as const;

export function flowIndex(phase: TripPhase | "brief"): number {
  switch (phase) {
    case "brief":
      return 0;
    case "searching":
      return 1;
    case "picking":
      return 2;
    case "who":
      return 3;
    default:
      return 4;
  }
}
