import { Check } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import { Stamp } from "@/components/ui/stamp";
import { Typewriter } from "@/components/ui/typewriter";
import { KIND_FILL, KindIcon } from "@/features/proposals";
import type { BookingResponse, BookingStatus } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { useArrivedAt } from "@/lib/motion";
import { cn } from "@/lib/utils";

const WORKING: ReadonlySet<BookingStatus> = new Set(["running", "approved"]);

export function isWorking(status: BookingStatus): boolean {
  return WORKING.has(status);
}

/** A lime band sweeping along the card's top edge while the agent is buying. Decorative. */
export function AgentWorkingBar({ active }: { active: boolean }): ReactNode {
  if (!active) return null;
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute inset-x-0 top-0 h-1 overflow-hidden rounded-t-[var(--radius-panel)]"
    >
      <span className="working-sweep absolute inset-y-0 left-0 w-2/5 rounded-full bg-gradient-to-r from-transparent via-lime to-transparent" />
    </span>
  );
}

/** "Replaced" stamped across a booking a disruption made obsolete, with its title struck. */
export function ReplacedStamp({ status }: { status: BookingStatus }): ReactNode {
  if (status !== "cancelled") return null;
  return (
    <span className="pointer-events-none absolute top-1/2 right-[22%] z-10 -translate-y-1/2">
      <Stamp tone="danger" rotate={-9} delayMs={150}>
        replaced
      </Stamp>
    </span>
  );
}

/** The line drawn through a replaced booking's title. Place inside a `relative` title. */
export function StrikeLine({ active }: { active: boolean }): ReactNode {
  if (!active) return null;
  return (
    <span
      aria-hidden
      className="strike-draw absolute top-1/2 left-0 h-0.5 w-full rounded-full bg-danger"
      style={{ "--delay": "100ms" } as CSSProperties}
    />
  );
}

type BookingTicketProps = { booking: BookingResponse; currency: string };

/**
 * A confirmed booking as the ticket it now is. When the confirmation lands while the page is
 * open, the ticket prints out of a slot and the booking ref types in; on a reload it is
 * simply there. Renders nothing for any other status.
 */
export function BookingTicket({ booking, currency }: BookingTicketProps): ReactNode {
  const printing = useArrivedAt(booking.status, "confirmed", 60_000);
  if (booking.status !== "confirmed") return null;
  const passengers = booking.passenger_user_ids.length;

  return (
    <div className="px-3 pb-3 sm:px-4 sm:pb-4">
      {/* The slot the ticket feeds out of. */}
      <div
        aria-hidden
        className="relative z-10 h-2 rounded-full bg-surface-sunken ring-1 ring-line"
      />
      <div className="-mt-1 mx-1.5 overflow-hidden rounded-b-[24px]">
        <section
          aria-label={`Ticket: ${booking.title}`}
          className={cn("text-pastel-ink", printing && "ticket-print")}
        >
          <div className={cn("rounded-[24px]", KIND_FILL[booking.kind])}>
            <div className="flex items-center justify-between gap-3 px-5 pt-5">
              <span className="ticket-mono text-[11px] uppercase">Ticket · {booking.supplier}</span>
              <span className="inline-flex items-center gap-1 rounded-full bg-pastel-ink px-2.5 py-0.5 text-xs text-lime">
                <Check className="size-3.5" strokeWidth={3} aria-hidden />
                booked
              </span>
            </div>
            <div className="flex items-end justify-between gap-3 px-5 pt-3 pb-4">
              <p className="min-w-0 text-lg leading-snug tracking-[-0.02em]">{booking.title}</p>
              <KindIcon kind={booking.kind} mode={booking.mode} className="size-6 shrink-0" />
            </div>
            <div className="relative" aria-hidden>
              <span className="absolute -left-2.5 top-1/2 size-5 -translate-y-1/2 rounded-full bg-surface" />
              <span className="absolute -right-2.5 top-1/2 size-5 -translate-y-1/2 rounded-full bg-surface" />
              <div className="perforation mx-5 [--color-line:rgb(0_0_0/0.35)]" />
            </div>
            <div className="flex flex-wrap items-end justify-between gap-3 px-5 pt-3 pb-5">
              <div>
                <p className="ticket-mono text-[10px] uppercase opacity-60">Booking ref</p>
                {booking.confirmation_ref ? (
                  <Typewriter
                    text={booking.confirmation_ref}
                    animate={printing}
                    delayMs={1000}
                    className="text-xl"
                  />
                ) : (
                  <p className="ticket-mono text-xl">—</p>
                )}
              </div>
              <p className="ticket-mono text-sm">
                {passengers > 0 ? `×${passengers} · ` : ""}
                {formatMoney(booking.amount_minor, currency)}
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
