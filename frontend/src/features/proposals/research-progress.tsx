import { Check } from "lucide-react";
import { type CSSProperties, type ReactNode, useEffect, useState } from "react";

import { TypingIndicator } from "@/components/ui/typing-indicator";
import { usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";

/**
 * What the agent looks through while researching. Presentational: the backend reports only
 * "proposing", so the ticks are a paced sequence that says what is being searched — not a
 * claim about which call returned first.
 */
export const RESEARCH_SOURCES = ["PKP Intercity", "Duffel flights", "Hotels", "Things to do"];

const TICK_MS = 900;

/** How many sources show as checked `elapsedTicks` into the search; the last stays open. */
export function checkedCount(elapsedTicks: number, total: number): number {
  return Math.max(0, Math.min(total - 1, elapsedTicks));
}

function useTicks(active: boolean): number {
  const [ticks, setTicks] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setTicks((value) => value + 1), TICK_MS);
    return () => window.clearInterval(timer);
  }, [active]);
  return ticks;
}

type ResearchProgressProps = {
  sources?: readonly string[];
  className?: string;
};

/** "The agent is searching": supplier ticks over three shimmering ticket placeholders. */
export function ResearchProgress({
  sources = RESEARCH_SOURCES,
  className,
}: ResearchProgressProps): ReactNode {
  const reduced = usePrefersReducedMotion();
  const ticks = useTicks(!reduced);
  const checked = reduced ? 0 : checkedCount(ticks, sources.length);

  return (
    <div className={cn("space-y-4", className)}>
      <div role="status" className="rounded-xl bg-agent-bg px-4 py-3.5 text-agent-fg">
        <p className="flex items-center gap-2 text-[15px]">
          <span className="text-xs font-medium text-agent-tag">Razor Trip agent</span>
          <TypingIndicator className="text-agent-tag" />
        </p>
        <p className="mt-1 text-[15px]">Researching trains, flights, stays and things to do…</p>
        <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Sources">
          {sources.map((source, index) => {
            const done = index < checked;
            const current = index === checked;
            return (
              <li
                key={source}
                className={cn(
                  "ticket-mono inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs transition-colors duration-300",
                  done
                    ? "bg-sun text-sun-ink"
                    : current
                      ? "bg-white/10 text-agent-fg"
                      : "bg-white/5 text-agent-fg/45",
                )}
              >
                {done ? (
                  <Check key="done" className="pop size-3" strokeWidth={3} aria-hidden />
                ) : (
                  <span
                    aria-hidden
                    className={cn(
                      "size-1.5 rounded-full bg-current",
                      current && "animate-pulse motion-reduce:animate-none",
                    )}
                  />
                )}
                {source}
                <span className="sr-only">{done ? " searched" : current ? " searching" : ""}</span>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="grid gap-3" aria-hidden>
        {[0, 1, 2].map((index) => (
          <TicketSkeleton key={index} index={index} />
        ))}
      </div>
    </div>
  );
}

/** A ticket-shaped placeholder: title, three item rows, a perforated stub. */
function TicketSkeleton({ index }: { index: number }): ReactNode {
  return (
    <div
      className="rise-in overflow-hidden rounded-[var(--radius-panel)] border border-line bg-surface"
      style={{ "--i": index } as CSSProperties}
    >
      <div className="space-y-3 px-6 pt-6">
        <div className="shimmer h-5 w-1/2 rounded-full bg-surface-sunken" />
        {[0, 1, 2].map((row) => (
          <div key={row} className="shimmer h-12 rounded-xl bg-surface-sunken" />
        ))}
      </div>
      <div className="perforation mx-6 mt-5" />
      <div className="flex items-center justify-between px-6 py-5">
        <div className="shimmer h-6 w-28 rounded-full bg-surface-sunken" />
        <div className="shimmer h-9 w-20 rounded-full bg-surface-sunken" />
      </div>
    </div>
  );
}
