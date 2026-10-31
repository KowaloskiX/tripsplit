import { Sparkles } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { Avatar } from "@/components/ui/avatar";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { TypingIndicator } from "@/components/ui/typing-indicator";
import type { EventKind, EventResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";

type Variant = "agent" | "mine" | "member" | "system";

export function variantOf(event: EventResponse, myUserId: string): Variant {
  if (event.actor === "agent") return "agent";
  if (event.kind !== "message") return "system";
  return event.actor_user_id === myUserId ? "mine" : "member";
}

// Agent events that change what people owe get a tag, so they do not drown in the chat.
const AGENT_TAG: Partial<Record<EventKind, { label: string; tone: BadgeTone }>> = {
  price_changed: { label: "price changed", tone: "warn" },
  resplit: { label: "new shares", tone: "warn" },
  disruption: { label: "disruption", tone: "danger" },
  refund_issued: { label: "refund", tone: "info" },
  all_paid: { label: "all paid", tone: "success" },
  booking_confirmed: { label: "booked", tone: "success" },
  booking_failed: { label: "failed", tone: "danger" },
};

/** A member's payment shows up as a green pill: money in. */
const SYSTEM_PILL: Partial<Record<EventKind, string>> = {
  contribution_paid: "bg-success-soft text-success",
  member_left: "bg-danger-soft text-danger",
};

/** Per-supplier search reports ("PKP Intercity ✓ 2 offers · 13.0 s") are progress, not talk:
 *  the chat leaves them out and the packages panel shows the research while it runs. */
export function isConversation(event: EventResponse): boolean {
  return !("supplier_progress" in event.payload);
}

/** The group total in the "everyone paid" message — the one money event without an amount. */
export function totalOf(event: EventResponse): number | null {
  const total = event.payload.total_minor;
  return event.kind === "all_paid" && typeof total === "number" ? total : null;
}

function time(iso: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(
    new Date(iso),
  );
}

/** How long the agent "types" before a fresh message of its appears. */
export const AGENT_TYPING_MS = 600;

/** Where a fresh message slides in from: members from the left, you and the agent from the right. */
const ENTRANCE: Record<Variant, string> = {
  agent: "feed-in-right",
  mine: "feed-in-right",
  member: "feed-in-left",
  system: "rise-in",
};

/** `true` for the first AGENT_TYPING_MS of a fresh agent message's life. */
function useTyping(fresh: boolean): boolean {
  const reduced = usePrefersReducedMotion();
  const [typing, setTyping] = useState(fresh && !reduced);
  useEffect(() => {
    if (!typing) return;
    const timer = window.setTimeout(() => setTyping(false), AGENT_TYPING_MS);
    return () => window.clearTimeout(timer);
  }, [typing]);
  return typing;
}

function AgentAvatar(): ReactNode {
  return (
    <span className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-agent-bg text-agent-tag ring-1 ring-line">
      <Sparkles className="size-3.5" aria-hidden />
    </span>
  );
}

type FeedItemProps = { event: EventResponse; variant: Variant; currency: string; fresh: boolean };

function FeedItem({ event, variant, currency, fresh }: FeedItemProps): ReactNode {
  const typing = useTyping(fresh && variant === "agent");
  const entrance = fresh ? ENTRANCE[variant] : undefined;
  if (typing) {
    return (
      <li className="feed-in-right flex items-start gap-2.5">
        <AgentAvatar />
        <span className="inline-flex h-11 items-center rounded-3xl rounded-tl-md bg-agent-bg px-4 text-agent-tag ring-1 ring-line">
          <TypingIndicator />
          <span className="sr-only">The agent is typing</span>
        </span>
      </li>
    );
  }
  if (variant === "system") {
    return (
      <li className={cn("flex justify-center", entrance)}>
        <span
          className={cn(
            "inline-flex max-w-full items-center gap-2 rounded-full px-2.5 py-0.5 text-[11px]",
            SYSTEM_PILL[event.kind] ?? "text-muted",
          )}
        >
          <span className="min-w-0">{event.message}</span>
          <span className="ticket-mono shrink-0 font-normal opacity-70">
            {time(event.created_at)}
          </span>
        </span>
      </li>
    );
  }
  if (variant === "agent") {
    const tag = AGENT_TAG[event.kind];
    const total = totalOf(event);
    return (
      <li className={cn("flex items-start gap-2.5", entrance)}>
        <AgentAvatar />
        <div className="min-w-0 max-w-[88%] rounded-2xl rounded-tl-md bg-agent-bg px-3.5 py-2.5 text-agent-fg ring-1 ring-line">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            <span className="font-medium text-agent-tag">Razor Trip agent</span>
            <span className="ticket-mono text-agent-fg/60">{time(event.created_at)}</span>
            {tag && <Badge tone={tag.tone}>{tag.label}</Badge>}
            {total !== null && (
              <span className="tabular-nums text-agent-fg/60">{formatMoney(total, currency)}</span>
            )}
          </p>
          <p className="mt-1 text-sm leading-relaxed">{event.message}</p>
        </div>
      </li>
    );
  }
  const mine = variant === "mine";
  const name = event.actor_name ?? "Member";
  return (
    <li className={cn("flex items-end gap-2", mine && "flex-row-reverse", entrance)}>
      {!mine && <Avatar name={name} size="sm" />}
      <div
        className={cn(
          "min-w-0 max-w-[80%] rounded-2xl px-3.5 py-2",
          mine
            ? "rounded-br-md bg-pastel-sea text-pastel-ink"
            : "rounded-bl-md bg-surface-sunken text-ink",
        )}
      >
        <p className={cn("text-xs", mine ? "text-pastel-ink/70" : "text-muted")}>
          <span className={cn("font-medium", !mine && "text-ink")}>{mine ? "You" : name}</span> ·{" "}
          <span className="ticket-mono">{time(event.created_at)}</span>
        </p>
        <p className="mt-0.5 whitespace-pre-wrap break-words text-sm leading-relaxed">
          {event.message}
        </p>
      </div>
    </li>
  );
}

type FeedListProps = {
  events: EventResponse[];
  myUserId: string;
  currency?: string;
};

/** Presentational: the group chat — agent, members and system events visually distinct. */
export function FeedList({ events, myUserId, currency = "PLN" }: FeedListProps): ReactNode {
  // What was already there when the list first rendered stays still; only arrivals animate.
  const initial = useRef<ReadonlySet<string> | null>(null);
  if (initial.current === null) initial.current = new Set(events.map((event) => event.id));
  const seen = initial.current;

  if (events.length === 0) {
    return <p className="py-8 text-center text-sm text-muted">Nothing here yet.</p>;
  }
  return (
    <ol className="space-y-3" aria-label="Trip feed">
      {events.map((event) => (
        <FeedItem
          key={event.id}
          event={event}
          variant={variantOf(event, myUserId)}
          currency={currency}
          fresh={!seen.has(event.id)}
        />
      ))}
    </ol>
  );
}
