import { Check, X } from "lucide-react";
import type { ReactNode } from "react";

import type { StepStatus } from "@/features/agent-graph";
import { cn } from "@/lib/utils";

import type { GraphStep } from "./model";

const DOT: Record<StepStatus, string> = {
  pending: "border border-dashed border-line bg-surface",
  running: "halo bg-sun",
  done: "bg-ink text-bg",
  healed: "bg-pastel-blush text-pastel-ink",
  failed: "bg-danger-soft text-danger",
};

function settled(status: StepStatus): boolean {
  return status === "done" || status === "healed";
}

/** The purchase run in one line: dots light up in sequence, a glow travels the live edge. */
export function GraphStrip({ steps }: { steps: readonly GraphStep[] }): ReactNode {
  const current = steps.find((step) => step.status === "running");
  return (
    <div className="min-w-0 rounded-xl bg-surface-sunken px-3 py-3">
      <p className="sr-only" aria-live="polite">
        {current ? `Now: ${current.label}` : ""}
      </p>
      <ol className="flex items-center" aria-label="Steps of the purchase">
        {steps.map((step, index) => (
          <li
            key={step.id}
            data-status={step.status}
            className={cn("flex items-center", index < steps.length - 1 && "flex-1")}
            title={step.label}
          >
            <span
              className={cn(
                "relative inline-flex size-6 shrink-0 items-center justify-center rounded-full transition duration-300",
                DOT[step.status],
                settled(step.status) && "settle",
              )}
            >
              {settled(step.status) && <Check className="size-3" strokeWidth={3} aria-hidden />}
              {step.status === "failed" && <X className="size-3" strokeWidth={3} aria-hidden />}
              <span className="sr-only">
                {step.label}: {step.status}
              </span>
            </span>
            {index < steps.length - 1 && (
              <span
                aria-hidden
                className="relative mx-1 h-0.5 flex-1 overflow-hidden rounded-full bg-line"
              >
                <span
                  className={cn(
                    "absolute inset-0 origin-left rounded-full bg-ink transition-transform duration-500",
                    settled(step.status) ? "scale-x-100" : "scale-x-0",
                  )}
                />
                {step.status === "running" && (
                  <span className="edge-travel-x absolute inset-y-0 left-0 w-1/2 rounded-full bg-gradient-to-r from-transparent via-sun to-transparent" />
                )}
              </span>
            )}
          </li>
        ))}
      </ol>
      <p className="mt-2 truncate text-xs text-muted">
        {current
          ? `▸ ${current.label}`
          : steps.every((step) => settled(step.status)) && steps.length > 0
            ? "▸ run complete"
            : "▸ waiting to start"}
      </p>
    </div>
  );
}
