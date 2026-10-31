import { Check } from "lucide-react";
import { type CSSProperties, type ReactNode, useRef } from "react";

import { KIND_FILL, KindIcon } from "@/features/proposals";
import { cn } from "@/lib/utils";

import type { MissionTicket } from "./model";

/** Where each fresh ticket flies in from: the browser (left) or the stay pane (right). */
function flight(ticket: MissionTicket): CSSProperties {
  const fromStay = ticket.kind === "stay";
  return {
    "--fly-x": fromStay ? "160px" : "-160px",
    "--fly-y": "-200px",
    "--fly-rot": fromStay ? "14deg" : "-14deg",
  } as CSSProperties;
}

/** Each ticket rests a little askew, like paper tossed onto a pile. */
const REST = [
  { rotate: -2.5, x: 0 },
  { rotate: 1.8, x: 10 },
  { rotate: -1, x: -6 },
  { rotate: 2.6, x: 4 },
];

type TicketStackProps = { tickets: readonly MissionTicket[]; purchases: number };

/** Finished purchases land here as tickets, one on top of the other. */
export function TicketStack({ tickets, purchases }: TicketStackProps): ReactNode {
  const initial = useRef<ReadonlySet<string> | null>(null);
  if (initial.current === null) initial.current = new Set(tickets.map((ticket) => ticket.id));
  const seen = initial.current;

  return (
    <section aria-label="Tickets" className="flex flex-col items-center gap-3">
      <div className="relative h-36 w-full max-w-sm">
        {tickets.length === 0 && (
          <div className="absolute inset-0 rounded-[24px] border-2 border-dashed border-line" />
        )}
        {tickets.map((ticket, index) => {
          const rest = REST[index % REST.length] ?? { rotate: 0, x: 0 };
          return (
            <article
              key={ticket.id}
              aria-label={`Ticket ${ticket.title}, booking ref ${ticket.ref}`}
              className={cn(
                "absolute inset-x-0 top-0 rounded-[24px] p-4 text-pastel-ink shadow-pop",
                KIND_FILL[ticket.kind],
                !seen.has(ticket.id) && "ticket-fly",
              )}
              style={
                {
                  ...flight(ticket),
                  translate: `${rest.x}px ${index * -6}px`,
                  rotate: `${rest.rotate}deg`,
                  zIndex: index + 1,
                } as CSSProperties
              }
            >
              <div className="flex items-center justify-between gap-3">
                <span className="ticket-mono text-[10px] uppercase">
                  Ticket · {ticket.supplier}
                </span>
                <KindIcon kind={ticket.kind} mode={ticket.mode} className="size-5" />
              </div>
              <p className="mt-2 truncate text-lg tracking-[-0.02em]">{ticket.title}</p>
              <div className="perforation my-2.5 [--color-line:rgb(0_0_0/0.35)]" />
              <div className="flex items-center justify-between">
                <span className="ticket-mono text-sm">{ticket.ref}</span>
                <span className="inline-flex items-center gap-1 rounded-full bg-pastel-ink px-2 py-0.5 text-[11px] text-lime">
                  <Check className="size-3" strokeWidth={3} aria-hidden />
                  booked
                </span>
              </div>
            </article>
          );
        })}
      </div>
      <p className="ticket-mono text-xs text-muted">
        {tickets.length}/{purchases} tickets
      </p>
    </section>
  );
}
