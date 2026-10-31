import { type CSSProperties, type ReactNode, useRef } from "react";

import { useInView } from "@/lib/motion";
import { cn } from "@/lib/utils";

type RevealProps = {
  children: ReactNode;
  className?: string;
  /** Position in a group revealed together: each one starts ~90 ms after the previous. */
  index?: number;
  /** Children marked `.cue` start their own animations only once this is on screen. */
  as?: "div" | "figure" | "li";
};

/**
 * Fades and lifts its content in the first time it scrolls into view. Hidden only while
 * scripts run (see `.reveal` in motion.css), so the content never depends on JavaScript.
 */
export function Reveal({ children, className, index = 0, as = "div" }: RevealProps): ReactNode {
  const ref = useRef<HTMLDivElement>(null);
  const visible = useInView(ref, "0px 0px -10% 0px");
  const Element = as;
  return (
    <Element
      // The same DOM node whichever tag is chosen; `useInView` only needs an Element.
      ref={ref as never}
      data-visible={visible}
      className={cn("reveal", className)}
      style={{ "--i": index } as CSSProperties}
    >
      {children}
    </Element>
  );
}
