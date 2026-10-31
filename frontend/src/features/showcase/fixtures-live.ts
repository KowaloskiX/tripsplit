/**
 * Fake data for the headline scenes (group phones, mission control, quick plan, trust UI).
 * Photos are drawn as inline SVGs so the rehearsal works offline.
 */
import type { PhoneState } from "@/features/group-phones";
import type { ApiCall, GraphStep, MissionTicket, StayStep } from "@/features/mission-control";
import type { ClarifyingQuestion, QuickPackage } from "@/features/quick-plan";
import type { TrustImage } from "@/features/trust";

import { MEMBERS } from "./fixtures";

/** A flat, made-up "photo": sky, a river and a skyline in the given hue. */
export function fakePhoto(hue: number, alt: string): TrustImage {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90"><defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="hsl(${hue} 70% 82%)"/><stop offset="1" stop-color="hsl(${(hue + 30) % 360} 60% 66%)"/></linearGradient></defs><rect width="160" height="90" fill="url(#s)"/><circle cx="122" cy="24" r="10" fill="hsl(${(hue + 50) % 360} 90% 90%)"/><path d="M0 62h14v-18h8v-10h6v10h8v18h10v-26l8-8 8 8v26h12v-14h10v-22h4v22h10v14h12v-20h10v20h14v-30h8v30h18v28H0z" fill="hsl(${hue} 30% 28%)"/><rect y="70" width="160" height="20" fill="hsl(${(hue + 190) % 360} 40% 40%)"/></svg>`;
  return { url: `data:image/svg+xml,${encodeURIComponent(svg)}`, alt };
}

const AMOUNT = 59_300;
const LINES = [
  "Old Town by train 🙌",
  "In!",
  "Paying now",
  "Can't wait 🍻",
  "Done ✓",
  "Booking the flat?",
];

/** The six phones after `voted` votes and `paid` payments have arrived. */
export function phones(voted: number, paid: number): PhoneState[] {
  return MEMBERS.map((member, index) => ({
    name: member.name,
    initials: member.name
      .split(" ")
      .map((part) => part[0])
      .join(""),
    last_message: index < Math.max(voted, paid) ? (LINES[index] ?? null) : null,
    voted_for: index < voted ? "Old Town by train" : null,
    paid: index < paid,
    amount: AMOUNT,
  }));
}

export const RUN_STEPS = [
  "Open search",
  "Pick EC 131",
  "Seats together",
  "6 passengers",
  "Contact email",
  "Summary",
  "Pay",
];

/** The run strip with `done` steps finished and the next one running. */
export function graphSteps(done: number): GraphStep[] {
  return RUN_STEPS.map((label, index) => ({
    id: `s${index}`,
    label,
    status: index < done ? "done" : index === done ? "running" : "pending",
  }));
}

const BASE = Date.parse("2026-11-20T12:04:30Z");
const CALLS: readonly Omit<ApiCall, "at">[] = [
  { method: "POST", path: "/air/offer_requests", status: 201, ms: 812, supplier: "duffel" },
  { method: "GET", path: "/air/offers/off_0000AqL", status: 200, ms: 214, supplier: "duffel" },
  { method: "POST", path: "/hotels/rates", status: 200, ms: 655, supplier: "liteapi" },
  { method: "POST", path: "/rates/prebook", status: 200, ms: 431, supplier: "liteapi" },
  { method: "POST", path: "/air/orders", status: 201, ms: 412, supplier: "duffel" },
  { method: "POST", path: "/rates/book", status: 409, ms: 188, supplier: "liteapi" },
  { method: "POST", path: "/rates/book", status: 200, ms: 702, supplier: "liteapi" },
  { method: "GET", path: "/air/orders/ord_0000AqM", status: 200, ms: 120, supplier: "duffel" },
];

export function calls(count: number): ApiCall[] {
  return CALLS.slice(0, count).map((call, index) => ({
    ...call,
    at: new Date(BASE + index * 1700).toISOString(),
  }));
}

export function staySteps(stage: number): StayStep[] {
  const state = (index: number): StayStep["state"] =>
    index < stage ? "done" : index === stage ? "running" : "pending";
  return [
    {
      key: "search",
      label: "Find the rate",
      state: state(0),
      ...(stage > 0 ? { detail: "1 320 zł" } : {}),
    },
    {
      key: "prebook",
      label: "Prebook · lock the price",
      state: state(1),
      ...(stage > 1 ? { detail: "locked 15 min" } : {}),
    },
    { key: "book", label: "Book", state: state(2), ...(stage > 2 ? { detail: "LITE-88213" } : {}) },
  ];
}

export const STAY_IMAGES = [
  fakePhoto(205, "Riverside flat, living room"),
  fakePhoto(28, "Riverside flat, view of the river"),
  fakePhoto(330, "Riverside flat, bedroom"),
];

export const TICKETS: readonly MissionTicket[] = [
  {
    id: "t-stay",
    title: "Riverside flat, Malá Strana",
    ref: "LITE-88213",
    supplier: "LiteAPI",
    kind: "stay",
    mode: null,
  },
  {
    id: "t-train",
    title: "EC 131 Warszawa → Praha",
    ref: "PKP-7Q4X-2291",
    supplier: "PKP Intercity",
    kind: "transport",
    mode: "rail",
  },
  {
    id: "t-flight",
    title: "LO 526 PRG → WAW",
    ref: "DFL-QK7M2P",
    supplier: "Duffel",
    kind: "transport",
    mode: "flight",
  },
];

const minutesAgo = (minutes: number): string =>
  new Date(Date.now() - minutes * 60_000).toISOString();

export function quickPackages(): QuickPackage[] {
  return [
    {
      id: "q1",
      title: "Old Town by train",
      stay: "Riverside flat, Malá Strana",
      images: [fakePhoto(205, "Riverside flat")],
      segments: [
        { mode: "rail", label: "EC 131 Warszawa → Praha · Fri 06:47" },
        { mode: "rail", label: "EC 130 Praha → Warszawa · Sun 16:12" },
      ],
      perPersonMinor: 59_300,
      provenance: { kind: "live", source: "PKP Intercity", checked_at: minutesAgo(2) },
      links: [
        { kind: "book", label: "Open on intercity.pl", url: "https://www.intercity.pl" },
        { kind: "map", label: "Hotel on map", url: "https://maps.google.com" },
      ],
    },
    {
      id: "q2",
      title: "Prague the fast way",
      stay: "Hotel Josef",
      images: [fakePhoto(28, "Hotel Josef")],
      segments: [
        { mode: "flight", label: "LO 525 WAW → PRG · Fri 07:05" },
        { mode: "flight", label: "LO 526 PRG → WAW · Sun 19:40" },
      ],
      perPersonMinor: 71_800,
      provenance: { kind: "test", source: "Duffel" },
      links: [
        { kind: "verify", label: "Check on Google Flights", url: "https://www.google.com/flights" },
        { kind: "status", label: "Flight status", url: "https://www.flightradar24.com" },
      ],
    },
    {
      id: "q3",
      title: "Budget weekend",
      stay: "Hostel Žižkov",
      images: [fakePhoto(120, "Hostel Žižkov")],
      segments: [{ mode: "bus", label: "FlixBus N 7003 Warszawa → Praha · Fri 22:30" }],
      perPersonMinor: 41_200,
      provenance: { kind: "example" },
      links: [],
    },
  ];
}

export const QUESTION: ClarifyingQuestion = {
  id: "people",
  text: "How many people?",
  options: ["2", "4", "6", "8"],
};
