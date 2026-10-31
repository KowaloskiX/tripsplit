import { Lock, MousePointer2 } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { cn } from "@/lib/utils";

import { GraphStrip } from "./graph-strip";
import type { BrowserMission } from "./model";

// One frame a second: the agent's screenshots change about that fast, and every request
// counts against the API's per-client rate limit (shared with the room's other polls).
const FRAME_MS = 1000;

/**
 * The newest frame that has actually loaded. Each tick preloads the next URL off-screen and
 * swaps only once it decoded — refreshing three times a second without a single blank flash.
 */
function useLiveFrame(frameSrc: ((tick: number) => string) | null | undefined): string | null {
  const [shown, setShown] = useState<string | null>(null);
  useEffect(() => {
    if (!frameSrc) return;
    let cancelled = false;
    let tick = 0;
    const load = (): void => {
      const url = frameSrc(tick++);
      const image = new Image();
      image.onload = () => {
        if (!cancelled) setShown(url);
      };
      image.src = url;
    };
    load();
    const timer = window.setInterval(load, FRAME_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [frameSrc]);
  return shown;
}

/** A stand-in checkout while no frame has arrived: form rows and the agent's cursor. */
function StandInPage(): ReactNode {
  return (
    <div
      aria-hidden
      // A light page inside the dark room: the shimmer reads its colour from --bg.
      className="relative size-full overflow-hidden bg-white p-5 text-black [--bg:#ffffff]"
    >
      <div className="flex items-center justify-between">
        <span className="h-4 w-24 rounded-full bg-black/80" />
        <span className="h-3 w-40 rounded-full bg-black/10" />
      </div>
      <div className="mt-6 grid grid-cols-2 gap-3">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="space-y-1.5">
            <span className="block h-2 w-16 rounded-full bg-black/15" />
            <span className="shimmer block h-9 rounded-xl border border-black/10 bg-black/[0.03]" />
          </div>
        ))}
      </div>
      <div className="mt-5 space-y-2">
        {[0, 1].map((index) => (
          <div
            key={index}
            className="flex items-center justify-between rounded-2xl border border-black/10 px-4 py-3"
          >
            <span className="h-3 w-40 rounded-full bg-black/15" />
            <span className="h-3 w-14 rounded-full bg-black/25" />
          </div>
        ))}
      </div>
      <span className="mt-5 ml-auto block h-10 w-36 rounded-full bg-[#c7ff9f]" />
      <span className="cursor-wander absolute inset-0">
        <MousePointer2 className="size-5 fill-black text-white drop-shadow" />
      </span>
    </div>
  );
}

type BrowserPaneProps = { browser: BrowserMission; live: boolean; className?: string };

/** The agent's browser: a framed live screenshot, the address bar, and the run as a strip. */
export function BrowserPane({ browser, live, className }: BrowserPaneProps): ReactNode {
  const frame = useLiveFrame(browser.frameSrc);
  return (
    <section
      aria-label="The agent's browser"
      className={cn("flex min-w-0 flex-col gap-3 rounded-[28px] bg-surface p-3", className)}
    >
      <div className="flex flex-1 flex-col overflow-hidden rounded-[20px] ring-1 ring-line">
        <div className="flex items-center gap-2 bg-surface-sunken px-3 py-2">
          <span aria-hidden className="flex gap-1.5">
            <span className="size-2.5 rounded-full bg-[#ff5f57]" />
            <span className="size-2.5 rounded-full bg-[#febc2e]" />
            <span className="size-2.5 rounded-full bg-[#28c840]" />
          </span>
          <span className="ticket-mono flex min-w-0 flex-1 items-center gap-1.5 truncate rounded-full bg-bg px-3 py-1 text-[11px] text-muted">
            <Lock className="size-3 shrink-0" aria-hidden />
            <span className="truncate">{browser.host}</span>
          </span>
          {live && (
            <span className="ticket-mono inline-flex items-center gap-1.5 rounded-full bg-lime px-2 py-0.5 text-[10px] uppercase text-pastel-ink">
              <span
                aria-hidden
                className="size-1.5 animate-pulse rounded-full bg-current motion-reduce:animate-none"
              />
              live
            </span>
          )}
        </div>
        <div className="relative aspect-[16/10] flex-1 bg-white lg:aspect-auto lg:min-h-[16rem]">
          {frame ? (
            <img
              src={frame}
              alt={`What the agent sees on ${browser.host}`}
              className="size-full object-cover object-top"
            />
          ) : (
            <StandInPage />
          )}
        </div>
      </div>
      <GraphStrip steps={browser.steps} />
    </section>
  );
}
