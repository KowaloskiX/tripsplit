import { Coffee, ExternalLink, MapPin, Route, Sparkles, Sun, Ticket } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import { Badge, type BadgeTone } from "@/components/ui/badge";
import type {
  ItemKind,
  ItineraryDayResponse,
  ItineraryItemResponse,
  TicketStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/** Pastel blocks: travel sky, attractions blush, meals lime, free time plain. */
const BLOCK: Record<ItemKind, string> = {
  travel: "bg-pastel-sky/70 text-pastel-ink",
  attraction: "bg-pastel-blush text-pastel-ink",
  meal: "bg-pastel-lime/80 text-pastel-ink",
  free: "bg-surface-sunken text-muted",
};

const ICON: Record<ItemKind, typeof Route> = {
  travel: Route,
  attraction: Sparkles,
  meal: Coffee,
  free: Sun,
};

const TICKETS: Record<TicketStatus, { label: string; tone: BadgeTone }> = {
  to_buy: { label: "tickets queued", tone: "outline" },
  buying: { label: "buying tickets", tone: "info" },
  booked: { label: "tickets booked", tone: "success" },
  needs_help: { label: "tickets need you", tone: "warn" },
};

export function TicketBadge({ status }: { status: TicketStatus }): ReactNode {
  const { label, tone } = TICKETS[status];
  return (
    <Badge tone={tone} pulse={status === "buying"} className={status === "booked" ? "pop" : ""}>
      <Ticket className="size-3" aria-hidden />
      {label}
    </Badge>
  );
}

function ItemBlock({ item, index }: { item: ItineraryItemResponse; index: number }): ReactNode {
  const Icon = ICON[item.kind];
  const compact = item.kind === "travel" || item.kind === "free";
  return (
    <li
      className="rise-in grid grid-cols-[3.25rem_minmax(0,1fr)] gap-2"
      style={{ "--i": index } as CSSProperties}
    >
      <span className="ticket-mono pt-2 text-right text-xs text-muted">
        {item.start}
        <span className="block text-[10px] opacity-70">{item.end}</span>
      </span>
      <div
        className={cn(
          "min-w-0 rounded-2xl px-3",
          compact ? "py-1.5" : "py-2.5",
          BLOCK[item.kind],
          item.tickets === "booked" && "ring-2 ring-success/60",
        )}
      >
        <p
          className={cn(
            "flex items-start gap-1.5 leading-snug",
            compact ? "text-xs" : "text-sm font-medium",
          )}
        >
          <Icon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span className="min-w-0">{item.title}</span>
        </p>
        {(item.note || item.tickets || item.map_url || item.link) && !compact && (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] opacity-80">
            {item.tickets && <TicketBadge status={item.tickets} />}
            {item.note && <span>{item.note}</span>}
            {item.map_url && (
              <a
                href={item.map_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-0.5 underline-offset-2 hover:underline"
              >
                <MapPin className="size-3" aria-hidden />
                Map
              </a>
            )}
            {item.link && (
              <a
                href={item.link}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-0.5 underline-offset-2 hover:underline"
              >
                <ExternalLink className="size-3" aria-hidden />
                Website
              </a>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

const DAY = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

/** Day columns with a time rail; on a phone they scroll sideways, one day per screen. */
export function ItineraryView({ days }: { days: readonly ItineraryDayResponse[] }): ReactNode {
  return (
    <div
      className="-mx-4 flex snap-x snap-mandatory gap-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0 lg:grid lg:overflow-visible"
      style={{ gridTemplateColumns: `repeat(${Math.max(days.length, 1)}, minmax(0, 1fr))` }}
    >
      {days.map((day) => (
        <section
          key={day.date}
          aria-label={`${day.label} plan`}
          className="w-[85%] shrink-0 snap-start sm:w-72 lg:w-auto"
        >
          <h3 className="mb-2 flex items-baseline gap-2 text-sm font-medium text-ink">
            {day.label}
            <span className="text-xs font-normal text-muted">
              {DAY.format(new Date(`${day.date}T12:00:00`))}
            </span>
          </h3>
          <ol className="space-y-1.5">
            {day.items.map((item, index) => (
              <ItemBlock key={`${item.start}-${item.title}`} item={item} index={index} />
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
