import { AlertTriangle, Check } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

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

// The current dot is see-through: the sliding indicator underneath gives it its colour.
const DOT: Record<StepState, string> = {
  done: "bg-accent text-accent-ink",
  current: "text-sun-ink",
  alert: "text-danger",
  upcoming: "border border-ink/15 bg-surface text-muted",
};

const LABEL: Record<StepState, string> = {
  done: "text-ink",
  current: "font-medium text-ink",
  alert: "font-medium text-danger",
  upcoming: "text-muted",
};

/** Where the indicator sits: the active step, or past the end once everything is done. */
export function activeIndexOf(steps: readonly Step[]): number {
  const active = steps.findIndex((step) => step.state === "current" || step.state === "alert");
  if (active >= 0) return active;
  return steps.every((step) => step.state === "done") ? steps.length - 1 : 0;
}

/**
 * A horizontal progress stepper. One track runs dot to dot and fills as steps complete; one
 * marigold indicator slides to the current step when the trip moves on (springy, transform only).
 */
export function Stepper({ steps, label, className }: StepperProps): ReactNode {
  const count = steps.length;
  const active = activeIndexOf(steps);
  const allDone = steps.every((step) => step.state === "done");
  const alert = steps[active]?.state === "alert";
  const fill = count > 1 ? active / (count - 1) : 1;
  const inset = `calc(100% / ${count * 2})`;

  return (
    <div className={cn("relative w-full", className)}>
      <span
        aria-hidden
        className="absolute top-3 h-px -translate-y-1/2 rounded-full bg-line"
        style={{ left: inset, right: inset }}
      >
        <span
          className="absolute inset-0 origin-left rounded-full bg-accent transition-transform duration-700 ease-[var(--ease-spring)]"
          style={{ transform: `scaleX(${fill})` }}
        />
      </span>
      {!allDone && (
        <span
          aria-hidden
          className="absolute top-0 left-0 flex h-6 justify-center transition-transform duration-500 ease-[var(--ease-spring)]"
          style={
            {
              width: `calc(100% / ${count})`,
              transform: `translateX(${active * 100}%)`,
            } as CSSProperties
          }
        >
          <span
            className={cn(
              "size-6 rounded-full transition-colors duration-300",
              alert ? "bg-pastel-blush [--halo-color:var(--color-danger)]" : "bg-sun",
            )}
          />
        </span>
      )}
      <ol aria-label={label} className="relative flex w-full items-start">
        {steps.map((step, index) => {
          const isActive = step.state === "current" || step.state === "alert";
          return (
            <li
              key={step.key}
              data-state={step.state}
              aria-current={isActive ? "step" : undefined}
              className="relative flex flex-1 flex-col items-center gap-1.5"
            >
              <span
                className={cn(
                  "ticket-mono relative z-10 inline-flex size-6 items-center justify-center rounded-full text-[11px] transition duration-300",
                  DOT[step.state],
                )}
              >
                {step.state === "done" ? (
                  <Check key="done" className="pop size-3.5" strokeWidth={2.5} aria-hidden />
                ) : step.state === "alert" ? (
                  <AlertTriangle className="size-3.5" aria-hidden />
                ) : (
                  index + 1
                )}
              </span>
              <span
                className={cn(
                  "max-w-[5.5rem] text-center text-[11px] leading-tight transition-colors duration-300 sm:max-w-none sm:text-[13px]",
                  LABEL[step.state],
                )}
              >
                {step.label}
                <span className="sr-only">
                  {step.state === "done" ? " (done)" : isActive ? " (current)" : ""}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
