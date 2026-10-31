/**
 * The data mission control draws. Presentational shapes, deliberately close to what the
 * backend already reports (run status steps, supplier call logs, booking refs), so wiring live
 * data is a mapping, not a redesign.
 */
import type { StepStatus } from "@/features/agent-graph";
import type { Provenance, TrustImage } from "@/features/trust";
import type { BookingKind, TransportMode } from "@/lib/api";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

/** One supplier API call, as the terminal prints it: `POST /air/orders 201 412ms`. */
export type ApiCall = {
  /** ISO time the call finished. */
  at: string;
  method: HttpMethod;
  path: string;
  status: number;
  ms: number;
  /** Who was called: "duffel", "liteapi". */
  supplier?: string;
};

/** A node of the agent's purchase run, flattened for the strip under the browser. */
export type GraphStep = {
  id: string;
  label: string;
  status: StepStatus;
};

export type StayStepKey = "search" | "prebook" | "book";
export type StayStepState = "pending" | "running" | "done" | "failed";

export type StayStep = {
  key: StayStepKey;
  label: string;
  state: StayStepState;
  /** "price locked for 15 min", "LITE-88213". */
  detail?: string;
};

export type StayMission = {
  title: string;
  supplier: string;
  amountMinor: number;
  images: readonly TrustImage[];
  provenance: Provenance;
  steps: readonly StayStep[];
};

/** A finished purchase, printed into the ticket stack. */
export type MissionTicket = {
  id: string;
  title: string;
  ref: string;
  supplier: string;
  kind: BookingKind;
  mode: TransportMode | null;
};

export type BrowserMission = {
  /** Live frame URL for a given refresh tick (cache-buster); absent = a stand-in page. */
  frameSrc?: ((tick: number) => string) | null;
  /** The supplier site the agent is on, shown in the address bar. */
  host: string;
  steps: readonly GraphStep[];
};

export type MissionControlData = {
  title: string;
  currency: string;
  /** Purchases in the basket; the header counts tickets against it. */
  purchases: number;
  browser: BrowserMission;
  /** Supplier API log; `null` = not available (hide the terminal). */
  calls: readonly ApiCall[] | null;
  stay?: StayMission | null;
  tickets: readonly MissionTicket[];
};

/** `12:04:31  POST /air/orders  201  412ms` — fixed-width columns for the terminal. */
export function formatCall(call: ApiCall): string {
  const time = new Date(call.at).toISOString().slice(11, 19);
  return `${time}  ${call.method.padEnd(6)} ${call.path}  ${call.status}  ${call.ms}ms`;
}

export type CallTone = "ok" | "redirect" | "client" | "server";

export function callTone(status: number): CallTone {
  if (status >= 500) return "server";
  if (status >= 400) return "client";
  if (status >= 300) return "redirect";
  return "ok";
}
