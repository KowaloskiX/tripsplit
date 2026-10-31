import type { CSSProperties, ReactNode } from "react";

import { digitsOf, useCountUp } from "@/lib/motion";
import { cn } from "@/lib/utils";

const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] as const;

type DigitRollProps = {
  value: number;
  minDigits?: number;
  className?: string;
};

/**
 * An integer as odometer reels: when it changes, each digit rolls to its new place. Screen
 * readers get the plain number; the reels are decoration.
 */
export function DigitRoll({ value, minDigits = 1, className }: DigitRollProps): ReactNode {
  const digits = digitsOf(value, minDigits);
  return (
    <span className={cn("ticket-mono inline-flex", className)}>
      <span className="sr-only">{Math.floor(value)}</span>
      <span aria-hidden className="inline-flex">
        {digits.map((digit, place) => (
          <span
            // Reels are keyed from the right, so 9 -> 10 adds a reel instead of reshuffling.
            // biome-ignore lint/suspicious/noArrayIndexKey: a reel is its place value.
            key={digits.length - place}
            className="relative inline-block h-[1lh] w-[1ch] overflow-hidden"
          >
            <span
              className="digit-reel absolute inset-x-0 top-0 flex flex-col"
              style={{ transform: `translateY(${-digit * 10}%)` } as CSSProperties}
            >
              {DIGITS.map((d) => (
                <span key={d} className="h-[1lh] text-center">
                  {d}
                </span>
              ))}
            </span>
          </span>
        ))}
      </span>
    </span>
  );
}

type CountUpProps = {
  /** The number to settle on, e.g. an amount in minor units. */
  value: number;
  /** Turns the in-between numbers into text, e.g. `formatMoney`. */
  format: (value: number) => string;
  durationMs?: number;
  /** Count from zero on mount (a reveal) instead of only on change. */
  fromZero?: boolean;
  className?: string;
};

/** A number that counts towards each new value instead of jumping to it. */
export function CountUp({
  value,
  format,
  durationMs = 700,
  fromZero = false,
  className,
}: CountUpProps): ReactNode {
  const shown = useCountUp(value, { durationMs, fromZero });
  return (
    <span className={cn("tabular-nums", className)}>
      <span className="sr-only">{format(value)}</span>
      <span aria-hidden>{format(shown)}</span>
    </span>
  );
}
