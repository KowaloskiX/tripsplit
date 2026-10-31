import { ChevronDown } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

type DisclosureProps = Omit<ComponentProps<"details">, "title"> & {
  /** The always-visible line; clicking it opens the rest. */
  summary: ReactNode;
  /** Classes for the summary row. */
  summaryClassName?: string;
};

/**
 * Progressive disclosure: a quiet summary row, the details only on request. A native
 * `<details>`, so it works without JavaScript and needs no state.
 */
export function Disclosure({
  summary,
  summaryClassName,
  className,
  children,
  ...props
}: DisclosureProps): ReactNode {
  return (
    <details className={cn("group/disclosure", className)} {...props}>
      <summary
        className={cn(
          "flex cursor-pointer list-none items-center justify-between gap-3 rounded-[var(--radius-control)] text-sm text-muted transition duration-150 hover:text-ink [&::-webkit-details-marker]:hidden",
          summaryClassName,
        )}
      >
        <span className="min-w-0">{summary}</span>
        <ChevronDown
          className="size-4 shrink-0 transition duration-200 group-open/disclosure:rotate-180"
          aria-hidden
        />
      </summary>
      {children}
    </details>
  );
}

type FoldedSectionProps = Omit<ComponentProps<"details">, "title"> & {
  title: ReactNode;
  /** A short state on the right ("6/6 paid", "12 ideas"). */
  hint?: ReactNode;
};

/**
 * A secondary part of a page, folded into one quiet row until someone wants it. The content
 * (usually its own panel) appears below the row.
 */
export function FoldedSection({
  title,
  hint,
  className,
  children,
  ...props
}: FoldedSectionProps): ReactNode {
  return (
    <details className={cn("group/folded", className)} {...props}>
      <summary className="flex cursor-pointer list-none items-center gap-3 rounded-[var(--radius-panel)] border border-line bg-surface px-4 py-3 text-[15px] text-ink transition duration-150 hover:border-ink/20 group-open/folded:mb-3 sm:px-5 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 flex-1 truncate font-medium">{title}</span>
        {hint && <span className="shrink-0 text-[13px] text-muted">{hint}</span>}
        <ChevronDown
          className="size-4 shrink-0 text-muted transition duration-200 group-open/folded:rotate-180"
          aria-hidden
        />
      </summary>
      {children}
    </details>
  );
}
