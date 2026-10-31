import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

const badge = cva(
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "bg-surface-sunken text-muted",
        /** Pastel fills always carry black text, in both themes. */
        sky: "bg-pastel-sea text-pastel-ink",
        sun: "bg-sun text-sun-ink",
        blush: "bg-pastel-blush text-pastel-ink",
        success: "bg-success-soft text-success",
        warn: "bg-warn-soft text-warn",
        danger: "bg-danger-soft text-danger",
        info: "bg-info-soft text-info",
        solid: "bg-accent text-accent-ink",
        outline: "border border-line text-muted",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeTone = NonNullable<VariantProps<typeof badge>["tone"]>;

type BadgeProps = ComponentProps<"span"> & {
  tone?: BadgeTone;
  /** A pulsing dot in front of the label — "this is happening right now". */
  pulse?: boolean;
};

export function Badge({
  className,
  tone,
  pulse = false,
  children,
  ...props
}: BadgeProps): ReactNode {
  return (
    <span data-tone={tone ?? "neutral"} className={cn(badge({ tone }), className)} {...props}>
      {pulse && (
        <span
          aria-hidden
          className="size-1.5 animate-pulse rounded-full bg-current motion-reduce:animate-none"
        />
      )}
      {children}
    </span>
  );
}
