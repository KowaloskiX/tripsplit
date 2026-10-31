import type { ReactNode } from "react";

import { ConfettiBurst } from "@/components/ui/confetti-burst";
import { DigitRoll } from "@/components/ui/number-roll";
import { Stamp } from "@/components/ui/stamp";
import { useArrivedAt } from "@/lib/motion";

import { BrowserPane } from "./browser-pane";
import type { MissionControlData } from "./model";
import { StayPane } from "./stay-pane";
import { TerminalPane } from "./terminal-pane";
import { TicketStack } from "./ticket-stack";

/**
 * The booking stage as a live control room: the agent's browser (with the run underneath),
 * the supplier API log, the stay's prebook → book, and every finished purchase printing into
 * a ticket stack. Presentational — the caller polls and passes data in.
 */
export function MissionControl({
  title,
  currency,
  purchases,
  browser,
  calls,
  stay,
  tickets,
}: MissionControlData): ReactNode {
  const done = purchases > 0 && tickets.length >= purchases;
  const celebrate = useArrivedAt(done, true, 3000);
  const live = !done;

  return (
    <section
      aria-label="Mission control"
      className="dark relative overflow-hidden rounded-[40px] bg-bg p-3 text-ink sm:p-4"
    >
      <header className="flex flex-wrap items-end justify-between gap-3 px-3 pt-3 pb-4 sm:px-4">
        <div className="min-w-0">
          <p className="eyebrow flex items-center gap-2">
            {live && (
              <span
                aria-hidden
                className="size-1.5 animate-pulse rounded-full bg-lime motion-reduce:animate-none"
              />
            )}
            Mission control
          </p>
          <h2 className="mt-1.5 text-2xl tracking-[-0.03em] text-ink sm:text-3xl">{title}</h2>
        </div>
        <p className="ticket-mono text-3xl text-ink sm:text-4xl" aria-live="polite">
          <span className="sr-only">
            {tickets.length} of {purchases} purchases done
          </span>
          <span aria-hidden>
            <DigitRoll value={tickets.length} />
            <span className="text-muted">/{purchases}</span>
          </span>
        </p>
      </header>

      <div className="grid items-stretch gap-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,0.85fr)]">
        <BrowserPane browser={browser} live={live} />
        <div className="flex min-w-0 flex-col gap-3">
          {calls && <TerminalPane calls={calls} />}
          {stay && <StayPane stay={stay} currency={currency} />}
        </div>
        <div className="relative flex flex-col justify-center rounded-[28px] bg-surface px-4 pt-8 pb-5 lg:col-span-2 xl:col-span-1">
          <p className="eyebrow absolute top-4 left-5">Tickets</p>
          <TicketStack tickets={tickets} purchases={purchases} />
          {celebrate && (
            <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <ConfettiBurst count={32} spread={190} />
              <Stamp tone="lime" rotate={-8} delayMs={500}>
                all booked
              </Stamp>
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
