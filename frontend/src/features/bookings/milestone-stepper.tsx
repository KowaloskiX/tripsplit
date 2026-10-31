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
    <ol className="flex flex-wrap items-center gap-1.5 text-xs font-medium" aria-label="Progress">
      {CHECKOUT_STEPS.map((step, index) => (
        <li
          key={step}
          aria-current={index === current ? "step" : undefined}
          className={cn(
            "rounded-full px-2.5 py-0.5 capitalize",
            index < current && "bg-ink text-bg",
            index === current && "bg-lime text-pastel-ink",
            index > current && "bg-surface-sunken text-muted",
          )}
        >
          {step}
        </li>
      ))}
    </ol>
  );
}
