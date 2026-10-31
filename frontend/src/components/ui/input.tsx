import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

export const CONTROL_CLASS = cn(
  "w-full rounded-[var(--radius-control)] border border-line bg-surface px-3.5 text-[15px] text-ink",
  "transition duration-150 placeholder:text-muted/70",
  "hover:border-muted/40 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/15",
  "aria-invalid:border-danger aria-invalid:focus-visible:ring-danger/15",
);

export function Input({ className, ...props }: ComponentProps<"input">): ReactNode {
  return <input className={cn(CONTROL_CLASS, "h-11", className)} {...props} />;
}
