import { AlertTriangle, Check } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type StepState = "done" | "current" | "alert" | "upcoming";

export type Step = {
  key: string;
  label: string;
  state: StepState;
};

type StepperProps = {
  steps: readonly Step[];
  label: string;
  className?: string;
};

const DOT: Record<StepState, string> = {
  done: "bg-ink text-bg",
  current: "halo bg-lime text-pastel-ink",
  alert: "halo bg-pastel-blush text-danger [--halo-color:var(--color-danger)]",
  upcoming: "border border-ink/15 bg-surface text-muted",
};

const LABEL: Record<StepState, string> = {
  done: "text-ink",
  current: "font-medium text-ink",
  alert: "font-medium text-danger",
  upcoming: "text-muted",
};

/** A horizontal progress stepper: dots joined by a line that fills as steps complete. */
export function Stepper({ steps, label, className }: StepperProps): ReactNode {
  return (
    <ol aria-label={label} className={cn("flex w-full items-start", className)}>
      {steps.map((step, index) => {
        const active = step.state === "current" || step.state === "alert";
        const last = index === steps.length - 1;
        return (
          <li
            key={step.key}
            data-state={step.state}
            aria-current={active ? "step" : undefined}
            className="relative flex flex-1 flex-col items-center gap-2"
          >
            {!last && (
              <span
                aria-hidden
                className={cn(
                  "absolute top-4 left-1/2 h-0.5 w-full rounded-full",
                  step.state === "done" ? "bg-ink" : "bg-line",
                )}
              />
            )}
            <span
              className={cn(
                "ticket-mono relative z-10 inline-flex size-8 items-center justify-center rounded-full text-xs transition duration-150",
                DOT[step.state],
              )}
            >
              {step.state === "done" ? (
                <Check className="size-4" strokeWidth={2.5} aria-hidden />
              ) : step.state === "alert" ? (
                <AlertTriangle className="size-4" aria-hidden />
              ) : (
                index + 1
              )}
            </span>
            <span
              className={cn(
                "max-w-[5.5rem] text-center text-[11px] leading-tight sm:max-w-none sm:text-sm",
                LABEL[step.state],
              )}
            >
              {step.label}
              <span className="sr-only">
                {step.state === "done" ? " (done)" : active ? " (current)" : ""}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
