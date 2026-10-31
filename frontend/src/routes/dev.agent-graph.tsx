import { createFileRoute, notFound } from "@tanstack/react-router";
import { Pause, Play, RotateCcw } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  AgentRunGraph,
  DEMO_RAIL_GRAPH,
  DEMO_RAIL_STEPS,
  DEMO_RAIL_TOTAL_MS,
  stepsAt,
} from "@/features/agent-graph";

const TICK_MS = 100;
const SPEEDS = [1, 2, 4] as const;
type Speed = (typeof SPEEDS)[number];

export const Route = createFileRoute("/dev/agent-graph")({
  // A story-like page for the demo: the fixture run replayed on a clock, no backend needed.
  beforeLoad: () => {
    if (!import.meta.env.DEV) throw notFound();
  },
  ssr: false,
  component: AgentGraphStory,
});

/** A clock that runs while `playing`, stops at `endMs`, and can be reset. */
function usePlayback(endMs: number, speed: Speed) {
  const [elapsed, setElapsed] = useState(0);
  const [playing, setPlaying] = useState(true);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setElapsed((ms) => Math.min(endMs, ms + TICK_MS * speed));
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, [playing, speed, endMs]);
  const finished = elapsed >= endMs;
  return {
    elapsed,
    playing: playing && !finished,
    toggle: () => (finished ? setElapsed(0) : setPlaying((value) => !value)),
    restart: () => {
      setElapsed(0);
      setPlaying(true);
    },
  };
}

function AgentGraphStory(): ReactNode {
  const [speed, setSpeed] = useState<Speed>(2);
  const playback = usePlayback(DEMO_RAIL_TOTAL_MS, speed);
  const steps = useMemo(() => stepsAt(DEMO_RAIL_STEPS, playback.elapsed), [playback.elapsed]);

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8 sm:px-6 lg:py-12">
      <div>
        <p className="eyebrow">Dev · fixture replay</p>
        <h1 className="display mt-3 text-5xl text-ink">Agent run graph</h1>
        <p className="mt-2 max-w-xl text-base text-muted">
          The demo rail purchase from <code className="font-mono text-sm">fixtures.ts</code>,
          replayed on a clock exactly as a polled{" "}
          <code className="font-mono text-sm">status.json</code> would report it.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={playback.toggle}>
          {playback.playing ? (
            <Pause className="size-4" aria-hidden />
          ) : (
            <Play className="size-4" aria-hidden />
          )}
          {playback.playing ? "Pause" : "Play"}
        </Button>
        <Button size="sm" variant="outline" onClick={playback.restart}>
          <RotateCcw className="size-4" aria-hidden />
          Restart
        </Button>
        <fieldset className="ml-auto flex items-center gap-1 rounded-full bg-surface-sunken p-1">
          <legend className="sr-only">Playback speed</legend>
          {SPEEDS.map((value) => (
            <Button
              key={value}
              size="sm"
              variant={value === speed ? "solid" : "ghost"}
              className="h-7 px-3"
              aria-pressed={value === speed}
              onClick={() => setSpeed(value)}
            >
              {value}×
            </Button>
          ))}
        </fieldset>
      </div>

      <AgentRunGraph
        graph={DEMO_RAIL_GRAPH}
        steps={steps}
        title="EC 131 Warszawa → Praha · 3 passengers"
      />
    </div>
  );
}
