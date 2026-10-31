import { Check } from "lucide-react";
import type { ReactNode } from "react";

import type { TripStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STEPS = [
  { key: "collecting", label: "Collecting" },
  { key: "voting", label: "Voting" },
  { key: "paying", label: "Paying" },
  { key: "booking", label: "Booking" },
  { key: "booked", label: "Booked" },
] as const;

/** Where each trip status sits on the five-step happy path. */
const STEP_OF: Record<TripStatus, number> = {
  collecting: 0,
  proposing: 0,
  voting: 1,
  paying: 2,
  booking: 3,
  booked: 4,
  disrupted: 4,
  rebooking: 4,
  done: 4,
};

export function StatusStepper({ status }: { status: TripStatus }): ReactNode {
  const current = STEP_OF[status];
  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-2" aria-label="Trip progress">
      {STEPS.map((step, index) => {
        const done = index < current || (index === current && status === "done");
        const active = index === current && !done;
        return (
          <li key={step.key} className="flex items-center gap-2">
            <span
              aria-current={active ? "step" : undefined}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.12em]",
                done && "border-live/40 bg-live/10 text-live",
                active && "border-accent bg-accent text-accent-ink",
                !done && !active && "border-line text-muted",
              )}
            >
              {done && <Check className="size-3" aria-hidden />}
              {step.label}
            </span>
            {index < STEPS.length - 1 && <span className="h-px w-4 bg-line" aria-hidden />}
          </li>
        );
      })}
    </ol>
  );
}
