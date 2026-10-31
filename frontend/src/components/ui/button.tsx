import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

const button = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium",
    "transition duration-150 ease-[var(--ease-calm)] active:translate-y-px",
    "disabled:pointer-events-none disabled:opacity-50",
  ],
  {
    variants: {
      variant: {
        /** Black pill on white, white pill on black. */
        solid: "bg-accent text-accent-ink hover:opacity-85",
        outline:
          "border border-ink/15 bg-transparent text-ink hover:border-ink/40 hover:bg-ink/[0.03]",
        ghost: "text-muted hover:bg-surface-sunken hover:text-ink",
        /** The one highlight: lime with black text. */
        lime: "bg-lime text-pastel-ink hover:brightness-95",
        danger: "border border-danger/40 bg-transparent text-danger hover:bg-danger-soft",
      },
      size: {
        lg: "h-14 px-7 text-[17px]",
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
