import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export const CHECKOUT_STEPS = ["search", "results", "passengers", "review", "done"] as const;
export type CheckoutStep = (typeof CHECKOUT_STEPS)[number];

/** The planner reports finer phases than the group needs to see; fold them onto five. */
const STEP_OF_MILESTONE: Record<string, CheckoutStep> = {
  browsing: "search",
  search: "search",
  results: "results",
  cart: "passengers",
  account: "passengers",
  passengers: "passengers",
  address: "passengers",
  delivery: "passengers",
  payment: "review",
  review: "review",
  summary: "review",
  done: "done",
};

export function stepIndexOf(milestone: string | null | undefined): number {
  const step = milestone ? STEP_OF_MILESTONE[milestone] : undefined;
  return step ? CHECKOUT_STEPS.indexOf(step) : -1;
}

export function MilestoneStepper({
  milestone,
  finished = false,
}: {
  milestone: string | null | undefined;
  /** A confirmed booking shows every step as reached, whatever the last milestone was. */
  finished?: boolean;
}): ReactNode {
  const current = finished ? CHECKOUT_STEPS.length - 1 : stepIndexOf(milestone);
  return (
    <ol className="flex flex-wrap items-center gap-1.5 font-mono text-[11px]" aria-label="Progress">
      {CHECKOUT_STEPS.map((step, index) => (
        <li
          key={step}
          aria-current={index === current ? "step" : undefined}
          className={cn(
            "rounded-full border px-2 py-0.5",
            index < current && "border-live/40 text-live",
            index === current && "border-accent bg-accent text-accent-ink",
            index > current && "border-line text-muted",
          )}
        >
          {step}
        </li>
      ))}
    </ol>
  );
}
