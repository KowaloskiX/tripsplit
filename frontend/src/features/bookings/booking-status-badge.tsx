import type { ReactNode } from "react";

import type { BookingStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

export type BadgeTone = "neutral" | "live" | "attention" | "success" | "danger" | "muted";

type StatusMeta = { label: string; tone: BadgeTone };

/** Every booking state the backend can report, as a person would say it. */
export const BOOKING_STATUS_META: Record<BookingStatus, StatusMeta> = {
  pending: { label: "Not started", tone: "neutral" },
  running: { label: "Agent working", tone: "live" },
  awaiting_approval: { label: "Needs approval", tone: "attention" },
  approved: { label: "Paying", tone: "live" },
  confirmed: { label: "Confirmed", tone: "success" },
  handoff: { label: "Needs a human", tone: "attention" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Replaced", tone: "muted" },
};

const TONE_CLASS: Record<BadgeTone, string> = {
  neutral: "bg-surface-sunken text-muted",
  live: "bg-sun text-sun-ink",
  attention: "bg-warn-soft text-warn",
  success: "bg-success-soft text-success",
  danger: "bg-danger-soft text-danger",
  muted: "bg-surface-sunken text-muted/70 line-through",
};

export function BookingStatusBadge({ status }: { status: BookingStatus }): ReactNode {
  const meta = BOOKING_STATUS_META[status];
  return (
    <span
      data-tone={meta.tone}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium",
        TONE_CLASS[meta.tone],
      )}
    >
      {meta.tone === "live" && (
        <span
          aria-hidden
          className="size-1.5 animate-pulse rounded-full bg-current motion-reduce:animate-none"
        />
      )}
      {meta.label}
    </span>
  );
}
