import { Mic } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";

const BAR_TICK_MS = 110;
const BARS = [0, 1, 2, 3] as const;

type MicOrbProps = {
  listening: boolean;
  /** 0..1 loudness stand-in; drives the ring and the bars. */
  level: number;
  size?: "md" | "lg";
  className?: string;
};

/** A bar's height (0..1): the level, rippled per bar so the four never move in lockstep. */
export function barScale(level: number, bar: number, phase: number): number {
  const ripple = 0.55 + 0.45 * Math.abs(Math.sin(phase * 0.9 + bar * 1.3));
  return Math.min(1, Math.max(0.2, 0.2 + level * ripple));
}

/**
 * The mic's face, presentational: an icon at rest; while listening a marigold disc with a pulsing
 * ring and four bars that follow the level. Transform and opacity only; reduced motion keeps
 * the bars at the level without the ripple and drops the pulse.
 */
export function MicOrb({ listening, level, size = "lg", className }: MicOrbProps): ReactNode {
  const reduced = usePrefersReducedMotion();
  const [phase, setPhase] = useState(0);
  useEffect(() => {
    if (!listening || reduced) return;
    const timer = window.setInterval(() => setPhase((value) => value + 1), BAR_TICK_MS);
    return () => window.clearInterval(timer);
  }, [listening, reduced]);

  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center rounded-full",
        size === "lg" ? "size-11" : "size-9",
        className,
      )}
    >
      {listening && (
        <>
          <span
            aria-hidden
            className="absolute inset-0 animate-ping rounded-full bg-sun/45 motion-reduce:animate-none"
          />
          <span
            aria-hidden
            className="absolute -inset-1 rounded-full ring-2 ring-sun/70 transition-transform duration-150 ease-out"
            style={{ transform: `scale(${1 + level * 0.3})` }}
          />
        </>
      )}
      <span
        className={cn(
          "relative inline-flex size-full items-center justify-center rounded-full transition-colors duration-150",
          listening ? "bg-sun text-sun-ink" : "text-muted hover:bg-surface-sunken hover:text-ink",
        )}
      >
        {listening ? (
          <span aria-hidden className="flex h-5 items-center gap-[3px]">
            {BARS.map((bar) => (
              <span
                key={bar}
                data-testid="mic-bar"
                className="h-5 w-[3px] rounded-full bg-current transition-transform duration-100 ease-out"
                style={{ transform: `scaleY(${barScale(level, bar, reduced ? 0 : phase)})` }}
              />
            ))}
          </span>
        ) : (
          <Mic className={size === "lg" ? "size-5" : "size-4"} aria-hidden />
        )}
      </span>
    </span>
  );
}
