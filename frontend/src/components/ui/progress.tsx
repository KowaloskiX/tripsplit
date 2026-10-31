import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type ProgressProps = {
  value: number;
  max: number;
  label: string;
  className?: string;
};

/** A determinate progress bar with an accessible name. */
export function Progress({ value, max, label, className }: ProgressProps): ReactNode {
  const percent = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      className={cn("h-2 w-full overflow-hidden rounded-full bg-surface-sunken", className)}
    >
      <div
        className="h-full rounded-full bg-live transition-[width]"
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
