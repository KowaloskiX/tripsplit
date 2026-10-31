/** API shapes -> what the chat shows: supplier ticks, journey legs, group messages. Pure. */
import type {
  EventKind,
  EventResponse,
  OptionResponse,
  QuickDraftResponse,
  SegmentResponse,
  TripResponse,
} from "@/lib/api";
import { formatMoney } from "@/lib/money";

// ---- step 1: what the agent understood ----------------------------------------------------

export type BriefChip = { label: string; value: string | null };

const MODE_LABEL: Record<string, string> = {
  rail: "Train",
  flight: "Plane",
  bus: "Bus",
};

function shortDate(iso: string): string {
  const date = new Date(`${iso}T12:00:00Z`);
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

export function dateRange(from: string | null, to: string | null): string | null {
  if (!from || !to) return null;
  return `${shortDate(from)} – ${shortDate(to)}`;
}

type BriefFields = {
  origin: string;
  destination: string | null;
  date_from: string | null;
  date_to: string | null;
  group_size: number | null;
  budget_per_person_minor: number | null;
  transport_mode: string | null;
};

function chips(fields: BriefFields, currency: string): BriefChip[] {
  return [
    { label: "From", value: fields.origin || null },
    { label: "To", value: fields.destination || null },
    { label: "Dates", value: dateRange(fields.date_from, fields.date_to) },
    { label: "People", value: fields.group_size ? String(fields.group_size) : null },
    {
      label: "Budget",
      value:
        fields.budget_per_person_minor !== null
          ? `${formatMoney(fields.budget_per_person_minor, currency)} pp`
          : "Any",
    },
    {
      label: "Travel by",
      value: fields.transport_mode ? (MODE_LABEL[fields.transport_mode] ?? null) : "Any",
    },
  ];
}

export function draftChips(draft: QuickDraftResponse): BriefChip[] {
  return chips(draft, "PLN");
}

export function tripChips(trip: TripResponse): BriefChip[] {
  return chips({ ...trip, destination: trip.destination || trip.title }, trip.currency);
}

// ---- step 2: suppliers ticked off ---------------------------------------------------------

export type SupplierTick = {
  id: string;
  supplier: string;
  outcome: "ok" | "empty" | "cached" | "failed" | "timeout";
  line: string;
};

type Progress = {
  supplier_id: string;
  supplier: string;
  kind: string;
  outcome: SupplierTick["outcome"];
  offers: number;
  seconds: number;
};

function progressOf(event: EventResponse): Progress | null {
  const raw = event.payload.supplier_progress;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const { supplier_id, supplier, kind, outcome, offers, seconds } = raw as Record<string, unknown>;
  if (typeof supplier !== "string" || typeof outcome !== "string") return null;
  return {
    supplier_id: typeof supplier_id === "string" ? supplier_id : supplier,
    supplier,
    kind: typeof kind === "string" ? kind : "",
    outcome: outcome as SupplierTick["outcome"],
    offers: typeof offers === "number" ? offers : 0,
    seconds: typeof seconds === "number" ? seconds : 0,
  };
}

function noun(progress: Progress): string {
  const id = progress.supplier_id.toLowerCase();
  if (progress.kind === "stay") return "stays";
  if (progress.kind === "activity") return id.includes("osm") ? "sights" : "things to do";
  if (id.includes("duffel") || id.includes("flight")) return "flights";
  if (id.includes("bus")) return "buses";
  return "trains";
}

/** "PKP Intercity ✓ 4 trains · 2.9 s" for every supplier of the latest research. */
export function supplierTicks(events: readonly EventResponse[]): SupplierTick[] {
  let start = 0;
  events.forEach((event, index) => {
    if (event.message.startsWith("Researching")) start = index;
  });
  const ticks = new Map<string, SupplierTick>();
  for (const event of events.slice(start)) {
    const progress = progressOf(event);
    if (!progress) continue;
    const took = progress.outcome === "cached" ? "cached" : `${progress.seconds.toFixed(1)} s`;
    const line =
      progress.outcome === "ok" || progress.outcome === "cached"
        ? `${progress.supplier} ✓ ${progress.offers} ${noun(progress)} · ${took}`
        : progress.outcome === "empty"
          ? `${progress.supplier} · nothing for these dates`
          : `${progress.supplier} ✗ ${progress.outcome === "timeout" ? "too slow" : "unavailable"}`;
    ticks.set(progress.supplier_id, {
      id: progress.supplier_id,
      supplier: progress.supplier,
      outcome: progress.outcome,
      line,
    });
  }
  return [...ticks.values()];
}

// ---- step 3: journeys ---------------------------------------------------------------------

export type Leg = {
  numbers: string;
  departs: string;
  arrives: string;
  duration: string;
  changes: number;
};

const NEW_LEG_GAP_MS = 6 * 3600_000;

function time(iso: string): string {
  const date = new Date(iso);
  const day = date.toLocaleDateString("en-GB", { weekday: "short" });
  const clock = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return `${day} ${clock}`;
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

export function duration(fromIso: string, toIso: string): string {
  const minutes = Math.max(0, Math.round((Date.parse(toIso) - Date.parse(fromIso)) / 60_000));
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}`;
}

/** Segments split into journeys (out, back) wherever the group waits more than 6 hours. */
export function legs(segments: readonly SegmentResponse[]): Leg[] {
  const groups: SegmentResponse[][] = [];
  for (const segment of segments) {
    const current = groups.at(-1);
    const previous = current?.at(-1);
    if (
      current &&
      previous &&
      Date.parse(segment.departs_at) - Date.parse(previous.arrives_at) < NEW_LEG_GAP_MS
    ) {
      current.push(segment);
    } else {
      groups.push([segment]);
    }
  }
  return groups.flatMap((group) => {
    const first = group[0];
    const last = group.at(-1);
    if (!first || !last) return [];
    return [
      {
        numbers: group.map((s) => s.number || s.carrier).join(" + "),
        departs: time(first.departs_at),
        arrives: clock(last.arrives_at),
        duration: duration(first.departs_at, last.arrives_at),
        changes: group.length - 1,
      },
    ];
  });
}

export function optionLegs(option: OptionResponse): Leg[] {
  return option.items.flatMap((item) => legs(item.segments));
}

export function changesLabel(changes: number): string {
  if (changes === 0) return "direct";
  return `${changes} change${changes === 1 ? "" : "s"}`;
}

/** The option's first photo, wherever an item has one. */
export function optionImage(option: OptionResponse): string | null {
  return option.items.flatMap((item) => item.images ?? [])[0] ?? null;
}

export function optionLinks(option: OptionResponse) {
  return option.items.flatMap((item) => item.links ?? []);
}

// ---- after the choice: the group in the same thread --------------------------------------

const GROUP_KINDS: ReadonlySet<EventKind> = new Set<EventKind>([
  "member_joined",
  "member_left",
  "contribution_paid",
  "all_paid",
  "booking_failed",
  "disruption",
  "resplit",
  "price_changed",
  "refund_issued",
  "funding_expired",
]);

export type GroupMessage = {
  id: string;
  /** null = the agent. */
  author: string | null;
  text: string;
  mine: boolean;
  tone: "info" | "warn";
};

/** What the friends do and say (and what goes wrong) after the trip was picked. */
export function groupMessages(
  events: readonly EventResponse[],
  myUserId: string | null,
): GroupMessage[] {
  const chosen = events.findIndex((event) => event.kind === "proposal_chosen");
  return events.flatMap((event, index): GroupMessage[] => {
    const typed = event.kind === "message" && event.actor === "member";
    const group = chosen >= 0 && index > chosen && GROUP_KINDS.has(event.kind);
    if (!typed && !group) return [];
    return [
      {
        id: event.id,
        author: event.actor === "agent" ? null : (event.actor_name ?? "Someone"),
        text: event.message,
        mine: typed && event.actor_user_id === myUserId,
        tone:
          event.kind === "disruption" ||
          event.kind === "booking_failed" ||
          event.kind === "funding_expired"
            ? "warn"
            : "info",
      },
    ];
  });
}
