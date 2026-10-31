import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

const button = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium",
    // A press sinks the pill a little and springs it back on release.
    "transition duration-150 ease-[var(--ease-calm)] active:scale-[0.97] active:duration-75",
    "motion-reduce:active:scale-100",
    "disabled:pointer-events-none disabled:opacity-50",
  ],
  {
    variants: {
      variant: {
        /** Ink on the light page, white on the dark one. */
        solid: "bg-accent text-accent-ink hover:opacity-90",
        outline:
          "border border-ink/15 bg-transparent text-ink hover:border-ink/40 hover:bg-ink/[0.03]",
        ghost: "text-muted hover:bg-surface-sunken hover:text-ink",
        /** The one highlight: coral with white text — the action that matters on the page. */
        sun: "bg-sun text-sun-ink hover:brightness-95",
        danger: "border border-danger/40 bg-transparent text-danger hover:bg-danger-soft",
      },
      size: {
        lg: "h-12 px-6 text-base",
        md: "h-11 px-5 text-sm",
        sm: "h-9 px-3.5 text-[13px]",
        icon: "size-9",
      },
    },
    defaultVariants: { variant: "solid", size: "md" },
  },
);

type ButtonProps = ComponentProps<"button"> &
  VariantProps<typeof button> & {
    /** Renders the child instead of a <button> — for links that look like buttons. */
    asChild?: boolean;
  };

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ButtonProps): ReactNode {
  const Component = asChild ? Slot : "button";
  return <Component className={cn(button({ variant, size }), className)} {...props} />;
}
