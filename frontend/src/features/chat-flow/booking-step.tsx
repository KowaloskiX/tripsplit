import { Ticket } from "lucide-react";
import { type CSSProperties, type ReactNode, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { useApproveAll, useMission, useStartAll, useTripBookings } from "@/features/bookings";
import { formatCall } from "@/features/mission-control";
import { apiErrorMessage, type BookingResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";

import { AgentMessage } from "./chat-bubbles";

const FRAME_MS = 700;

function useTick(active: boolean): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setTick((value) => value + 1), FRAME_MS);
    return () => window.clearInterval(timer);
  }, [active]);
  return tick;
}

/** The agent at work, small: its browser frame, the step it is on, the supplier API lines. */
function LiveStrip({ tripId, title }: { tripId: string; title: string }): ReactNode {
  const mission = useMission(tripId, title);
  const frameSrc = mission?.browser.frameSrc ?? null;
  const tick = useTick(frameSrc !== null);
  if (!mission) return null;
  const step = mission.browser.steps.at(-1);
  const calls = (mission.calls ?? []).slice(-3);
  return (
    <div className="overflow-hidden rounded-[24px] border border-line bg-surface shadow-card">
      <div className="flex gap-3 p-3">
        <div className="aspect-[4/3] w-32 shrink-0 overflow-hidden rounded-xl bg-surface-sunken sm:w-44">
          {frameSrc && (
            <img
              src={frameSrc(tick)}
              alt={`The agent on ${mission.browser.host}`}
              className="size-full object-cover object-top"
            />
          )}
        </div>
        <div className="min-w-0 space-y-1">
          <p className="ticket-mono truncate text-xs text-muted">{mission.browser.host}</p>
          <p className="text-sm text-ink">{step ? step.label.replaceAll("_", " ") : "starting…"}</p>
          <p className="text-xs text-muted">
            {mission.tickets.length} of {mission.purchases} booked
          </p>
        </div>
      </div>
      {calls.length > 0 && (
        <pre className="ticket-mono overflow-x-auto border-t border-line bg-surface-sunken px-3 py-2 text-[11px] leading-relaxed text-muted">
          {calls.map((call) => formatCall(call)).join("\n")}
        </pre>
      )}
    </div>
  );
}

function TicketCard({
  booking,
  currency,
  index,
}: {
  booking: BookingResponse;
  currency: string;
  index: number;
}): ReactNode {
  return (
    <li
      className="pop min-w-0 list-none rounded-[22px] border border-line bg-surface p-4 shadow-card"
      style={{ "--i": index } as CSSProperties}
      aria-label={`Ticket: ${booking.title}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          <Ticket className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-ink">{booking.title}</p>
            <p className="text-xs text-muted">{booking.supplier}</p>
          </div>
        </div>
        <span className="ticket-mono shrink-0 text-xs text-muted">
          {formatMoney(booking.amount_minor, currency)}
        </span>
      </div>
      <p className="mt-2 flex items-center justify-between gap-2">
        <span className="text-[11px] uppercase tracking-wide text-muted">booking ref</span>
        <span className="ticket-mono rounded-lg bg-surface-sunken px-2 py-0.5 text-sm text-ink">
          {booking.confirmation_ref ?? "confirmed"}
        </span>
      </p>
    </li>
  );
}

/**
 * Step 8: the agent narrates the purchases — starting them (unless AUTO_BOOK already did),
 * a live strip while it buys, one "Approve basket" button, then the tickets.
 */
export function BookingStep({ tripId, title }: { tripId: string; title: string }): ReactNode {
  const { data } = useTripBookings(tripId);
  const approve = useApproveAll(tripId);
  const start = useStartAll(tripId);
  if (!data) return null;
  const current = data.bookings.filter((booking) => booking.status !== "cancelled");
  const waiting = current.filter((booking) => booking.status === "awaiting_approval");
  const confirmed = current.filter((booking) => booking.status === "confirmed");
  const startable = current.filter(
    (booking) => booking.status === "pending" || booking.status === "failed",
  );
  const working = current.some(
    (booking) => booking.status === "running" || booking.status === "approved",
  );
  const total = waiting.reduce((sum, booking) => sum + booking.amount_minor, 0);
  const done = current.length > 0 && confirmed.length === current.length;
  const error = approve.error ?? start.error;

  return (
    <>
      {!done && (
        <AgentMessage
          label="Booking"
          wide
          text={
            working
              ? waiting.length > 0
                ? `${waiting.length} of ${current.length - confirmed.length} ready, still preparing the rest…`
                : "Booking everything…"
              : waiting.length > 0
                ? "Everything is ready at the suppliers. Nothing is paid until you approve."
                : "Everyone has paid. Shall I book it all?"
          }
        >
          {working && <LiveStrip tripId={tripId} title={title} />}
          {data.is_organizer && startable.length > 0 && !working && waiting.length === 0 && (
            <Button variant="sun" onClick={() => start.startAll()} disabled={start.isPending}>
              {start.isPending ? "Starting…" : "Book everything"}
            </Button>
          )}
          {/* One approval for the whole basket: offered once nothing is still being prepared. */}
          {data.is_organizer && waiting.length > 0 && !working && (
            <Button variant="sun" onClick={() => approve.approveAll()} disabled={approve.isPending}>
              {approve.isPending
                ? "Approving…"
                : `Approve basket (total ${formatMoney(total, data.currency)})`}
            </Button>
          )}
          {error && <ErrorCallout>{apiErrorMessage(error)}</ErrorCallout>}
        </AgentMessage>
      )}
      {confirmed.length > 0 && (
        <AgentMessage
          label="Tickets"
          wide
          text={
            done
              ? `Done — all ${confirmed.length} booked. Here are your tickets.`
              : `${confirmed.length} of ${current.length} booked so far.`
          }
        >
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {confirmed.map((booking, index) => (
              <TicketCard
                key={booking.id}
                booking={booking}
                currency={data.currency}
                index={index}
              />
            ))}
          </ul>
        </AgentMessage>
      )}
    </>
  );
}
