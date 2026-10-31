import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The Razor Trip logo: a sun cut clean in two — one trip, split fairly. The mark keeps its own
 * colours; the name inherits the text colour, so it works on light and on dark.
 */
export function LogoMark({ className }: { className?: string }): ReactNode {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-8 shrink-0", className)}>
      <rect width="32" height="32" rx="9" fill="#ff385c" />
      <circle cx="16" cy="16" r="8.5" fill="#fff" />
      <path d="M5 25 27 7" stroke="#ff385c" strokeWidth="2.75" strokeLinecap="round" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }): ReactNode {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 text-xl font-bold tracking-[-0.03em] leading-none",
        className,
      )}
    >
      <LogoMark className="size-[1.4em]" />
      Razor Trip
    </span>
  );
}
