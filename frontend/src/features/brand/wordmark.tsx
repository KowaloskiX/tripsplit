import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The tripsplit wordmark — plain text for now. The logo is being designed; when it lands, this
 * is the single component to swap. It inherits its colour, so it works on black and on white.
 */
export function Wordmark({ className }: { className?: string }): ReactNode {
  return (
    <span className={cn("text-2xl font-medium tracking-[-0.04em] leading-none", className)}>
      tripsplit
    </span>
  );
}
