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
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-surface-sunken",
        className,
      )}
    >
      {/* Slid, not resized: transform keeps it at 60 fps and lets the spring overshoot. The
          `before:` extension fills the gap an overshoot would open on the left. */}
      <div
        className={cn(
          "absolute inset-y-0 left-0 w-full rounded-full transition-transform duration-700 ease-[var(--ease-spring)]",
          "before:absolute before:inset-y-0 before:right-[calc(100%-1rem)] before:w-full before:bg-inherit",
          TONE[tone],
        )}
        style={{ transform: `translateX(${percent - 100}%)` }}
      />
    </div>
  );
}
