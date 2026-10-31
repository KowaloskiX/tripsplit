import { Check, Loader2, X } from "lucide-react";
import type { ReactNode } from "react";

import { isExample, PhotoStrip, ProvenancePill } from "@/features/trust";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import type { StayMission, StayStepState } from "./model";

const DOT: Record<StayStepState, string> = {
  pending: "border border-dashed border-line text-muted",
  running: "halo bg-sun text-sun-ink",
  done: "settle bg-ink text-bg",
  failed: "bg-danger-soft text-danger",
};

function StepIcon({ state, index }: { state: StayStepState; index: number }): ReactNode {
  if (state === "done") return <Check className="size-3.5" strokeWidth={3} aria-hidden />;
  if (state === "failed") return <X className="size-3.5" strokeWidth={3} aria-hidden />;
  if (state === "running") {
    return <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden />;
  }
  return <span className="ticket-mono text-xs">{index + 1}</span>;
}

type StayPaneProps = { stay: StayMission; currency: string; className?: string };

/** The stay, bought through the supplier's API: search → prebook (price locked) → book. */
export function StayPane({ stay, currency, className }: StayPaneProps): ReactNode {
  return (
    <section
      aria-label={`Stay: ${stay.title}`}
      className={cn("min-w-0 space-y-3 rounded-[var(--radius-panel)] bg-surface p-3", className)}
    >
      <div className="flex items-center gap-3">
        <PhotoStrip
          images={stay.images}
          max={1}
          example={isExample(stay.provenance)}
          className="w-24 shrink-0 rounded-2xl sm:w-28"
        />
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-base leading-snug tracking-[-0.01em] text-ink">{stay.title}</p>
          <p className="ticket-mono text-sm text-ink">{formatMoney(stay.amountMinor, currency)}</p>
          <ProvenancePill provenance={stay.provenance} />
        </div>
      </div>
      <ol className="space-y-1.5" aria-label="Stay purchase steps">
        {stay.steps.map((step, index) => (
          <li
            key={step.key}
            data-state={step.state}
            className={cn(
              "flex items-center gap-2.5 rounded-2xl px-2.5 py-2 transition-colors duration-300",
              step.state === "running" ? "bg-surface-sunken" : "",
            )}
          >
            <span
              key={step.state}
              className={cn(
                "inline-flex size-6 shrink-0 items-center justify-center rounded-full",
                DOT[step.state],
              )}
            >
              <StepIcon state={step.state} index={index} />
            </span>
            <span
              className={cn("flex-1 text-sm", step.state === "pending" ? "text-muted" : "text-ink")}
            >
              {step.label}
            </span>
            {step.detail && (
              <span key={step.detail} className="rise-in text-xs tabular-nums text-muted">
                {step.detail}
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
