import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Hourglass, Lock } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { activeAgentBooking, useTripBookings } from "@/features/bookings";
import {
  agentRunFrameUrl,
  agentRunsStatusOptions,
  type BookingResponse,
  type LiveStatusResponse,
} from "@/lib/api";
import { formatMoney } from "@/lib/money";

const FRAME_MS = 700;
const inBrowser = typeof window !== "undefined";

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** A cache-busting tick that advances only while the run is active (the last frame stays). */
function useFrameTick(active: boolean): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setTick((value) => value + 1), FRAME_MS);
    return () => window.clearInterval(timer);
  }, [active]);
  return tick;
}

/** Preloads each new frame off-screen and swaps it in once loaded: no flicker, no blank. */
function useLoadedFrame(src: string | null): string | null {
  const [shown, setShown] = useState<string | null>(null);
  useEffect(() => {
    if (!src) return;
    let current = true;
    const image = new Image();
    image.onload = () => {
      if (current) setShown(src);
    };
    image.src = src;
    return () => {
      current = false;
    };
  }, [src]);
  return shown;
}

/** The human sentence for where the agent is now, from the run's live status. */
export function stepLine(
  booking: BookingResponse,
  live: LiveStatusResponse | undefined,
  currency: string,
): string {
  const host = hostOf(booking.supplier_url);
  if (booking.status === "confirmed") return `Booked on ${host}`;
  if (booking.status === "awaiting_approval")
    return `Checking the summary: ${formatMoney(booking.amount_minor, currency)} ✓`;
  if (booking.status === "approved") return "Paying with the single-use card…";
  if (booking.status === "failed" || booking.status === "handoff")
    return live?.reason || "The agent stopped — a person needs to take over";
  const step = live?.steps.at(-1);
  const travellers = Math.max(booking.passenger_user_ids.length, 1);
  if (step?.kind === "fill_form") {
    if (step.iteration === null) return `Filling in ${travellers} passengers…`;
    const passenger = Math.min(step.iteration + 1, travellers);
    return `Filling passenger ${passenger} of ${travellers}…`;
  }
  switch (live?.milestone) {
    case "search":
      return `Searching trains on ${host}…`;
    case "results":
      return "Picking the train from the results…";
    case "passengers":
      return `Filling passenger details (${travellers})…`;
    case "review":
      return "Checking the summary…";
    default:
      return step ? `Working: ${step.kind.replaceAll("_", " ")}…` : `Opening ${host}…`;
  }
}

/** Share of the run done, 0..1: finished steps over all known ones (a done run is full). */
function progressOf(booking: BookingResponse, live: LiveStatusResponse | undefined): number {
  if (booking.status === "confirmed") return 1;
  const steps = live?.steps ?? [];
  if (steps.length === 0) return 0.04;
  const finished = steps.filter((step) => step.status !== "pending" && step.status !== "running");
  // The approval and the payment still follow the last site step.
  const ratio = finished.length / (steps.length + 1);
  return booking.status === "awaiting_approval" ? 0.9 : Math.min(Math.max(ratio, 0.04), 0.9);
}

/**
 * The agent's browser, big: a browser window with the supplier's host, the live frame (16:10,
 * full column width), the step it is on and a progress bar. Overlays say when it waits for
 * the approval and when the ticket is booked. Renders nothing until an agent run exists.
 */
export function LivePreview({ tripId }: { tripId: string }): ReactNode {
  const { data } = useTripBookings(tripId);
  const current = (data?.bookings ?? []).filter((booking) => booking.status !== "cancelled");
  const booking = activeAgentBooking(current);
  const runId = booking?.run?.run_id ?? "";
  const active = booking?.status === "running" || booking?.status === "approved";
  const status = useQuery({
    ...agentRunsStatusOptions({ path: { run_id: runId } }),
    enabled: inBrowser && runId !== "",
    refetchInterval: active ? FRAME_MS : false,
  });
  const tick = useFrameTick(active);
  const frame = useLoadedFrame(runId ? agentRunFrameUrl(runId, tick) : null);

  if (!data || !booking || !runId) return null;
  const live = status.data?.live;
  const host = hostOf(booking.supplier_url);
  const line = stepLine(booking, live, data.currency);
  const progress = progressOf(booking, live);
  const waiting = booking.status === "awaiting_approval";
  const booked = booking.status === "confirmed";

  return (
    <figure
      className="w-full overflow-hidden rounded-[var(--radius-panel)] border border-line bg-surface shadow-card"
      aria-label={`The agent's browser on ${host}`}
    >
      <div className="flex items-center gap-3 border-b border-line bg-surface-sunken px-3 py-2">
        <span className="flex shrink-0 gap-1.5" aria-hidden>
          <span className="size-2.5 rounded-full bg-danger" />
          <span className="size-2.5 rounded-full bg-warn" />
          <span className="size-2.5 rounded-full bg-success" />
        </span>
        <span className="ticket-mono flex min-w-0 flex-1 items-center gap-1.5 truncate rounded-full border border-line bg-surface px-3 py-1 text-xs text-muted">
          <Lock className="size-3 shrink-0" aria-hidden />
          <span className="truncate">{host}</span>
        </span>
        {active ? (
          <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-danger px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-surface">
            <span className="size-1.5 rounded-full bg-surface motion-safe:animate-pulse" />
            Live
          </span>
        ) : (
          <span className="shrink-0 rounded-full border border-line px-2 py-0.5 text-[11px] uppercase tracking-wide text-muted">
            {booked ? "Done" : waiting ? "Paused" : "Stopped"}
          </span>
        )}
      </div>

      <div className="relative aspect-[16/10] w-full bg-surface-sunken">
        {frame ? (
          <img
            src={frame}
            alt={`The agent on ${host}: ${line}`}
            className="size-full object-cover object-top"
          />
        ) : (
          <p className="grid size-full place-items-center text-sm text-muted" role="status">
            Opening {host}…
          </p>
        )}
        {waiting && (
          <div className="absolute inset-0 grid place-items-center bg-ink/40 motion-safe:transition-opacity">
            <p className="flex items-center gap-2 rounded-full bg-surface px-4 py-2 text-sm font-medium text-ink shadow-card">
              <Hourglass className="size-4 text-warn" aria-hidden />
              Waiting for your approval
            </p>
          </div>
        )}
        {booked && (
          <div className="absolute inset-0 grid place-items-center bg-success/30">
            <div className="flex flex-col items-center gap-1 rounded-[20px] bg-success px-6 py-3 text-surface shadow-card">
              <span className="flex items-center gap-2 text-lg font-semibold">
                <CheckCircle2 className="size-5" aria-hidden />
                Booked
              </span>
              {booking.confirmation_ref && (
                <span className="ticket-mono text-sm">{booking.confirmation_ref}</span>
              )}
            </div>
          </div>
        )}
      </div>

      <figcaption className="space-y-2 px-4 py-3">
        <p className="text-sm text-ink" aria-live="polite">
          {line}
        </p>
        <div
          className="h-1 w-full overflow-hidden rounded-full bg-surface-sunken"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
          aria-label="Booking progress"
        >
          <div
            className={`h-full rounded-full motion-safe:transition-[width] motion-safe:duration-500 ${booked ? "bg-success" : "bg-accent"}`}
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      </figcaption>
    </figure>
  );
}
