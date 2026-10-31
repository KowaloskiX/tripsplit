import { Bot } from "lucide-react";
import type { ReactNode } from "react";

import type { EventResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

type Variant = "agent" | "mine" | "member" | "system";

export function variantOf(event: EventResponse, myUserId: string): Variant {
  if (event.actor === "agent") return "agent";
  if (event.kind !== "message") return "system";
  return event.actor_user_id === myUserId ? "mine" : "member";
}

function time(iso: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(
    new Date(iso),
  );
}

function FeedItem({ event, variant }: { event: EventResponse; variant: Variant }): ReactNode {
  if (variant === "system") {
    return (
      <li className="py-1 text-center font-mono text-[11px] text-muted">
        {event.message} · {time(event.created_at)}
      </li>
    );
  }
  if (variant === "agent") {
    return (
      <li className="flex gap-2.5">
        <span className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-accent text-accent-ink">
          <Bot className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 max-w-[85%] rounded-[var(--radius-panel)] border border-accent/40 bg-accent/8 px-3 py-2">
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-accent">
            TripSplit agent · {time(event.created_at)}
          </p>
          <p className="mt-0.5 text-sm text-ink">{event.message}</p>
        </div>
      </li>
    );
  }
  const mine = variant === "mine";
  return (
    <li className={cn("flex", mine && "justify-end")}>
      <div
        className={cn(
          "min-w-0 max-w-[80%] rounded-[var(--radius-panel)] px-3 py-2",
          mine ? "bg-live text-accent-ink" : "border border-line bg-surface",
        )}
      >
        <p
          className={cn(
            "font-mono text-[10px] uppercase tracking-[0.14em]",
            mine ? "opacity-80" : "text-muted",
          )}
        >
          {mine ? "You" : (event.actor_name ?? "Member")} · {time(event.created_at)}
        </p>
        <p className={cn("mt-0.5 whitespace-pre-wrap break-words text-sm", !mine && "text-ink")}>
          {event.message}
        </p>
      </div>
    </li>
  );
}

type FeedListProps = {
  events: EventResponse[];
  myUserId: string;
};

/** Presentational: the group chat — agent, members and system events visually distinct. */
export function FeedList({ events, myUserId }: FeedListProps): ReactNode {
  if (events.length === 0) {
    return <p className="py-8 text-center text-sm text-muted">Nothing here yet.</p>;
  }
  return (
    <ol className="space-y-3" aria-label="Trip feed">
      {events.map((event) => (
        <FeedItem key={event.id} event={event} variant={variantOf(event, myUserId)} />
      ))}
    </ol>
  );
}
