import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

/** The card every section of the app sits on: white, rounded, a soft shadow. */
export function Panel({ className, ...props }: ComponentProps<"div">): ReactNode {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-panel)] border border-line bg-surface shadow-card",
        className,
      )}
      {...props}
    />
  );
}

export function PanelHeader({ className, ...props }: ComponentProps<"div">): ReactNode {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 border-b border-line px-6 py-4",
        "text-base font-medium tracking-tight text-ink [&>*:last-child:not(:first-child)]:font-medium [&>*:last-child:not(:first-child)]:text-muted",
        className,
      )}
      {...props}
    />
  );
}
