import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

const button = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-control)] font-medium",
    // A press sinks the pill a little and springs it back on release.
    "transition duration-150 ease-[var(--ease-calm)] active:scale-[0.98] active:duration-75",
    "motion-reduce:active:scale-100",
    "disabled:pointer-events-none disabled:opacity-50",
  ],
  {
    variants: {
      variant: {
        /** Ink on the light page, white on the dark one. */
        solid: "bg-accent text-accent-ink hover:opacity-90",
        outline:
          "border border-line bg-surface text-ink hover:border-ink/25 hover:bg-surface-sunken",
        ghost: "text-muted hover:bg-surface-sunken hover:text-ink",
        /** The one highlight: deep brown with cream text — the action that matters on the page. */
        sun: "bg-sun text-sun-ink shadow-[0_1px_2px_rgb(78_59_49/0.12)] hover:opacity-90",
        danger: "border border-danger/40 bg-transparent text-danger hover:bg-danger-soft",
      },
      size: {
        lg: "h-11 px-6 text-[15px]",
        md: "h-10 px-4 text-sm",
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
