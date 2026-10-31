import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const TONE = {
  accent: "bg-ink",
  success: "bg-success",
  warn: "bg-warn",
  lime: "bg-lime",
} as const;

type ProgressProps = {
  value: number;
  max: number;
  label: string;
  tone?: keyof typeof TONE;
  className?: string;
};

/** A determinate progress bar with an accessible name. */
export function Progress({
  value,
  max,
  label,
  tone = "accent",
  className,
}: ProgressProps): ReactNode {
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
        className={cn("h-full rounded-full transition-[width] duration-500", TONE[tone])}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
