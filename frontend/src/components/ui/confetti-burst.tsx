import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/lib/utils";

const COLORS = ["var(--lime)", "var(--pastel-sky)", "var(--pastel-blush)", "var(--pastel-lime)"];
const GOLDEN_ANGLE = 2.39996;

type Fleck = { dx: number; dy: number; rot: number; delay: number; color: string; wide: boolean };

/**
 * Deterministic flecks (no randomness: the same burst on the server and the client, and in a
 * screenshot): spread on a golden-angle spiral, thrown out and pulled down by "gravity".
 */
export function confettiFlecks(count: number, spread = 150): Fleck[] {
  return Array.from({ length: count }, (_, index) => {
    const angle = index * GOLDEN_ANGLE;
    const reach = spread * (0.45 + ((index * 37) % 55) / 100);
    return {
      dx: Math.round(Math.cos(angle) * reach),
      // Upwards throw, then a fall: biased down.
      dy: Math.round(Math.sin(angle) * reach * 0.7 + spread * 0.35),
      rot: ((index * 97) % 540) - 270,
      delay: (index % 6) * 30,
      color: COLORS[index % COLORS.length] ?? "var(--lime)",
      wide: index % 3 === 0,
    };
  });
}

type ConfettiBurstProps = { count?: number; spread?: number; className?: string };

/** A small, classy burst from the centre of its (relative) parent. Decorative only. */
export function ConfettiBurst({
  count = 28,
  spread = 150,
  className,
}: ConfettiBurstProps): ReactNode {
  return (
    <span
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0 flex items-center justify-center",
        className,
      )}
    >
      {confettiFlecks(count, spread).map((fleck, index) => (
        <span
          // biome-ignore lint/suspicious/noArrayIndexKey: flecks are positional and never reorder.
          key={index}
          className={cn(
            "confetti-fleck absolute rounded-[2px]",
            fleck.wide ? "h-1.5 w-3" : "size-2",
          )}
          style={
            {
              background: fleck.color,
              "--dx": `${fleck.dx}px`,
              "--dy": `${fleck.dy}px`,
              "--rot": `${fleck.rot}deg`,
              "--delay": `${fleck.delay}ms`,
            } as CSSProperties
          }
        />
      ))}
    </span>
  );
}
