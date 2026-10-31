/**
 * Live data for mission control, mapped from what the backend already reports: the trip's
 * bookings (polled), the active agent run's status, and the supplier call log.
 */
import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";

import type {
  ApiCall,
  GraphStep,
  HttpMethod,
  MissionControlData,
  MissionTicket,
  StayMission,
  StayStep,
} from "@/features/mission-control";
import { imagesFromApi, provenanceFromApi } from "@/features/trust";
import {
  agentRunFrameUrl,
  type BookingResponse,
  type BookingStatus,
  bookingsActivityOptions,
  type RunStepResponse,
  type SupplierCallResponse,
  type TripBookingsResponse,
  type TripStatus,
} from "@/lib/api";

import { useRunStatus, useTripBookings } from "./queries";

const ACTIVITY_POLL_MS = 1000;
const MISSION_STATUSES: ReadonlySet<TripStatus> = new Set(["booking", "rebooking"]);
const WORKING: ReadonlySet<BookingStatus> = new Set(["running", "approved", "awaiting_approval"]);
const HTTP_METHODS: ReadonlySet<string> = new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]);
const inBrowser = typeof window !== "undefined";

/** The agent run the browser pane should show: a working one first, else the latest. */
export function activeAgentBooking(
  bookings: readonly BookingResponse[],
): BookingResponse | undefined {
  const withRun = bookings.filter((booking) => booking.channel === "agent" && booking.run);
  return withRun.find((booking) => WORKING.has(booking.status)) ?? withRun.at(-1);
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function graphSteps(steps: readonly RunStepResponse[]): GraphStep[] {
  // `index` repeats across retries of a step; the position is unique.
  return steps.map((step, position) => ({
    id: `${position}-${step.index}`,
    label: step.node_id ?? step.kind,
    status: step.status,
  }));
}

export function apiCalls(calls: readonly SupplierCallResponse[]): ApiCall[] {
  return calls.map((call) => ({
    at: call.at,
    method: (HTTP_METHODS.has(call.method) ? call.method : "GET") as HttpMethod,
    path: call.path,
    status: call.status ?? 0,
    ms: call.ms,
    supplier: call.supplier,
  }));
}

function stayStepStates(status: BookingStatus): [StayStep["state"], StayStep["state"]] {
  switch (status) {
    case "pending":
      return ["pending", "pending"];
    case "running":
      return ["running", "pending"];
    case "awaiting_approval":
      return ["done", "pending"];
    case "approved":
      return ["done", "running"];
    case "confirmed":
      return ["done", "done"];
    case "failed":
    case "handoff":
    case "cancelled":
      return ["failed", "pending"];
  }
}

export function stayMission(booking: BookingResponse): StayMission {
  const [prebook, book] = stayStepStates(booking.status);
  return {
    title: booking.title,
    supplier: booking.supplier,
    amountMinor: booking.amount_minor,
    images: imagesFromApi(booking.images, booking.title),
    provenance: provenanceFromApi(booking.provenance) ?? { kind: "live", source: booking.supplier },
    steps: [
      { key: "search", label: "Search", state: "done", detail: booking.supplier },
      {
        key: "prebook",
        label: "Prebook",
        state: prebook,
        ...(prebook === "done" && book !== "done" ? { detail: "price locked" } : {}),
      },
      {
        key: "book",
        label: "Book",
        state: book,
        ...(booking.confirmation_ref ? { detail: booking.confirmation_ref } : {}),
      },
    ],
  };
}

function ticketOf(booking: BookingResponse): MissionTicket {
  return {
    id: booking.id,
    title: booking.title,
    ref: booking.confirmation_ref ?? "confirmed",
    supplier: booking.supplier,
    kind: booking.kind,
    mode: booking.mode,
  };
}

/** The purchases this booking round is about: everything not replaced or cancelled. */
function currentBookings(trip: TripBookingsResponse): BookingResponse[] {
  return trip.bookings.filter((booking) => booking.status !== "cancelled");
}

/** Supplier API calls of the trip; a missing endpoint (404) hides the terminal for good. */
function useActivity(tripId: string, active: boolean) {
  return useQuery({
    ...bookingsActivityOptions({ path: { trip_id: tripId } }),
    enabled: inBrowser && active,
    retry: false,
    refetchInterval: (query) =>
      active && query.state.status !== "error" ? ACTIVITY_POLL_MS : false,
  });
}

/** Mission control's data while a purchase is running; `null` = show the plain booking UI. */
export function useMission(tripId: string, title: string): MissionControlData | null {
  const bookings = useTripBookings(tripId);
  const trip = bookings.data;
  const live = trip !== undefined && MISSION_STATUSES.has(trip.trip_status);
  const current = trip ? currentBookings(trip) : [];
  const agent = activeAgentBooking(current);
  const runId = agent?.run?.run_id ?? "";
  const agentWorking = agent !== undefined && WORKING.has(agent.status);
  const status = useRunStatus(runId, live && agentWorking && runId !== "");
  const anyRunning = current.some(
    (booking) => WORKING.has(booking.status) || booking.status === "pending",
  );
  const activity = useActivity(tripId, live && anyRunning);
  const frameSrc = useCallback((tick: number) => agentRunFrameUrl(runId, tick), [runId]);

  // Only while something is actually being bought: the plain booking list says the rest.
  if (!trip || !live || !current.some((booking) => WORKING.has(booking.status))) return null;
  const stay = current.find((booking) => booking.kind === "stay");
  const tickets = current.filter((booking) => booking.status === "confirmed").map(ticketOf);
  const steps = status.data?.live.steps ?? [];
  return {
    title,
    currency: trip.currency,
    purchases: current.length,
    browser: {
      // Polled only while the agent works; the last frame stays on screen afterwards.
      frameSrc: runId && agentWorking ? frameSrc : null,
      host: agent ? hostOf(agent.supplier_url) : "waiting for the agent",
      steps: graphSteps(steps),
    },
    calls: activity.isError ? null : apiCalls(activity.data ?? []),
    stay: stay ? stayMission(stay) : null,
    tickets,
  };
}
