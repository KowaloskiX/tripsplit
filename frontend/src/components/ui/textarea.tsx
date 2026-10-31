import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Textarea({ className, ...props }: ComponentProps<"textarea">): ReactNode {
  return (
    <textarea
      className={cn(
        "min-h-20 w-full rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2 text-sm text-ink",
        "placeholder:text-muted/70 aria-invalid:border-danger",
        className,
      )}
      {...props}
    />
  );
}
