import { type ReactNode, useEffect, useState } from "react";

import { usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";

type TypewriterProps = {
  text: string;
  /** Milliseconds per character. */
  speedMs?: number;
  delayMs?: number;
  /** `false` shows the whole text at once — e.g. a ref that was already there on load. */
  animate?: boolean;
  className?: string;
};

/** Types `text` in one character at a time with a blinking caret, like a terminal printout. */
export function Typewriter({
  text,
  speedMs = 55,
  delayMs = 0,
  animate = true,
  className,
}: TypewriterProps): ReactNode {
  const reduced = usePrefersReducedMotion();
  const instant = reduced || !animate;
  const [count, setCount] = useState(instant ? text.length : 0);

  useEffect(() => {
    if (instant) {
      setCount(text.length);
      return;
    }
    setCount(0);
    let interval = 0;
    const start = window.setTimeout(() => {
      interval = window.setInterval(() => {
        setCount((value) => {
          if (value + 1 >= text.length) window.clearInterval(interval);
          return Math.min(text.length, value + 1);
        });
      }, speedMs);
    }, delayMs);
    return () => {
      window.clearTimeout(start);
      window.clearInterval(interval);
    };
  }, [text, speedMs, delayMs, instant]);

  const typing = count < text.length;
  return (
    <span className={cn("ticket-mono", className)}>
      <span className="sr-only">{text}</span>
      <span aria-hidden>
        {text.slice(0, count)}
        {typing && (
          <span className="caret ml-px inline-block h-[0.9em] w-[0.5ch] bg-current align-[-0.1em]" />
        )}
      </span>
    </span>
  );
}
