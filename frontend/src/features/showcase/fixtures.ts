/**
 * Fake trip data for the motion rehearsal (/dev/motion): a Prague weekend for six, shaped
 * exactly like the API responses, so the real components render it.
 */
import type {
  BookingResponse,
  BookingStatus,
  ContributionResponse,
  EventResponse,
  ProposalResponse,
  RoomResponse,
  TripBookingsResponse,
  TripStatus,
} from "@/lib/api";

export const CURRENCY = "PLN";
export const ME = "u1";

export const MEMBERS = [
  { id: "u1", name: "Ola Nowak" },
  { id: "u2", name: "Kuba Wiśniewski" },
  { id: "u3", name: "Maja Zielińska" },
  { id: "u4", name: "Tomek Lis" },
  { id: "u5", name: "Ewa Kowalska" },
  { id: "u6", name: "Piotr Wójcik" },
] as const;

const FRIDAY = "2026-12-04T06:47:00+01:00";

function item(
  kind: "transport" | "stay" | "activity",
  title: string,
  supplier: string,
  priceMinor: number,
  mode: "rail" | "flight" = "rail",
): ProposalResponse["items"][number] {
  const number = title.split(" ").slice(0, 2).join(" ");
  return {
    kind,
    mode: kind === "transport" ? mode : null,
    title,
    supplier,
    supplier_url: "https://example.com",
    price_minor: priceMinor,
    details: "",
    starts_at: FRIDAY,
    segments:
      kind === "transport"
        ? [
            {
              number,
              carrier: supplier,
              origin: mode === "flight" ? "WAW" : "Warszawa",
              destination: mode === "flight" ? "PRG" : "Praha",
              departs_at: FRIDAY,
              arrives_at: "2026-12-04T15:20:00+01:00",
            },
          ]
        : [],
  };
}

function proposal(
  id: string,
  title: string,
  summary: string,
  perPersonMinor: number,
  items: ProposalResponse["items"],
): ProposalResponse {
  return {
    id,
    title,
    summary,
    items,
    per_person_minor: perPersonMinor,
    total_minor: perPersonMinor * MEMBERS.length,
    votes: 0,
    voted_by_me: false,
    chosen: false,
    over_budget: false,
  };
}

export const PROPOSALS: readonly ProposalResponse[] = [
  proposal(
    "p1",
    "Old Town by train",
    "EC 131 there, a flat by the river, a beer tasting.",
    59_300,
    [
      item("transport", "EC 131 Warszawa → Praha", "PKP Intercity", 189_600),
      item("stay", "Riverside flat, Malá Strana", "Hotels", 132_000),
      item("activity", "Czech beer tasting", "Things to do", 34_200),
    ],
  ),
  proposal("p2", "Prague the fast way", "A morning flight and a design hotel.", 71_800, [
    item("transport", "LO 525 WAW → PRG", "Duffel flights", 254_400, "flight"),
    item("stay", "Hotel Josef", "Hotels", 156_000),
  ]),
  proposal("p3", "Budget weekend", "The night train and a hostel in Žižkov.", 41_200, [
    item("transport", "EN 407 Warszawa → Praha", "PKP Intercity", 132_000),
    item("stay", "Hostel Žižkov", "Hotels", 115_200),
  ]),
];

/** The proposals with these vote counts; `chosen` marks the winner once voting is over. */
export function withVotes(votes: readonly number[], chosen?: string): ProposalResponse[] {
  return PROPOSALS.map((p, index) => ({
    ...p,
    votes: votes[index] ?? 0,
    voted_by_me: index === 0 && (votes[0] ?? 0) > 0,
    chosen: p.id === chosen,
  }));
}

/** Shares of the winning package; the first `paid` members have paid. */
export function contributions(paid: number): ContributionResponse[] {
  const share = PROPOSALS[0]?.per_person_minor ?? 0;
  return MEMBERS.map((member, index) => {
    const done = index < paid;
    return {
      user_id: member.id,
      display_name: member.name,
      amount_minor: share,
      paid_minor: done ? share : 0,
      outstanding_minor: done ? 0 : share,
      refund_minor: 0,
      status: done ? "paid" : "pending",
    };
  });
}

export function room(status: TripStatus, proposals: ProposalResponse[], paid = 0): RoomResponse {
  const shares = status === "collecting" || status === "proposing" || status === "voting";
  return {
    trip: {
      id: "demo-trip",
      title: "Prague in December",
      brief: "Prague, a long weekend, under 700 zł each",
      origin: "Warszawa",
      destination: "Praha",
      date_from: "2026-12-04",
      date_to: "2026-12-06",
      group_size: MEMBERS.length,
      organizer_id: "u2",
      currency: CURRENCY,
      status,
      budget_per_person_minor: 70_000,
      chosen_proposal_id: proposals.find((p) => p.chosen)?.id ?? null,
      total_minor: PROPOSALS[0]?.total_minor ?? 0,
      transport_mode: "rail",
    },
    members: MEMBERS.map((member) => ({
      user_id: member.id,
      display_name: member.name,
      role: member.id === "u2" ? "organizer" : "member",
      traveller_details_complete: true,
      traveller_details_missing: [],
    })),
    // A member's view: no organizer buttons, so nothing in the rehearsal calls the API.
    my_role: "member",
    my_user_id: ME,
    my_vote_proposal_id: null,
    invite_code: "demo",
    proposals,
    contributions: shares ? [] : contributions(paid),
    my_contribution: null,
    paid_count: paid,
  };
}

type BookingPatch = Partial<Pick<BookingResponse, "confirmation_ref" | "replaces_booking_id">>;

export function booking(
  id: string,
  kind: "transport" | "stay",
  status: BookingStatus,
  patch: BookingPatch = {},
): BookingResponse {
  const train = kind === "transport";
  return {
    id,
    trip_id: "demo-trip",
    kind,
    mode: train ? "rail" : null,
    title: train ? "EC 131 Warszawa → Praha" : "Riverside flat, Malá Strana",
    supplier: train ? "PKP Intercity" : "Hotels",
    supplier_id: train ? "pkp_intercity" : "sim_stays",
    supplier_url: "https://example.com",
    channel: train ? "agent" : "api",
    amount_minor: train ? 189_600 : 132_000,
    passenger_user_ids: train ? MEMBERS.map((m) => m.id) : [],
    hold_expires_at: null,
    // No run: the live frame would poll the backend, and the rehearsal must not need one.
    run: null,
    status,
    confirmation_ref: null,
    replaces_booking_id: null,
    ...patch,
  };
}

export function bookings(
  status: TripStatus,
  list: BookingResponse[],
  totalMinor = 321_600,
): TripBookingsResponse {
  return {
    trip_id: "demo-trip",
    trip_status: status,
    currency: CURRENCY,
    is_organizer: false,
    total_minor: totalMinor,
    travellers: MEMBERS.length,
    bookings: list,
  };
}

let clock = Date.parse("2026-11-20T18:02:00+01:00");

function event(
  id: string,
  actor: EventResponse["actor"],
  kind: EventResponse["kind"],
  message: string,
  who?: (typeof MEMBERS)[number],
  payload: EventResponse["payload"] = {},
): EventResponse {
  clock += 60_000;
  return {
    id,
    actor,
    kind,
    message,
    actor_user_id: who?.id ?? null,
    actor_name: who?.name ?? null,
    created_at: new Date(clock).toISOString(),
    payload,
  };
}

const [ola, kuba, maja] = MEMBERS;

export const FEED: readonly EventResponse[] = [
  event("e1", "member", "message", "Prague in December? 🍻", maja),
  event("e2", "member", "message", "In, if it’s under 700 zł", kuba),
  event(
    "e3",
    "agent",
    "proposals_ready",
    "3 packages from 412 zł each. Vote, then pay your share — I’ll book.",
  ),
  event("e4", "member", "message", "Old Town by train, obviously", ola),
  event("e5", "system", "contribution_paid", "Maja paid 593 zł", maja),
  event(
    "e6",
    "agent",
    "all_paid",
    "Everyone paid — booking the train and the stay now.",
    undefined,
    {
      total_minor: 355_800,
    },
  ),
];
