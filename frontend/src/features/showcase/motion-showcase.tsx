import { Pause, Play, RotateCcw } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { DEMO_RAIL_TOTAL_MS } from "@/features/agent-graph";
import { usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { VoiceScene } from "./scene-voice";
import { LandingScene, PackagesScene, SharesScene, VotingScene } from "./scenes-early";
import {
  GroupPhonesScene,
  MissionControlScene,
  QuickPlanScene,
  TrustScene,
} from "./scenes-headline";
import { BookingScene, DisruptionScene, FeedScene, TransitionsScene } from "./scenes-late";

type Scene = {
  key: string;
  title: string;
  caption: string;
  durationMs: number;
  /** Narrow scenes render at the width of the room's stage column. */
  wide?: boolean;
  render: () => ReactNode;
};

export const SCENES: readonly Scene[] = [
  {
    key: "phones",
    title: "Six phones",
    caption:
      "Votes, then payments land on everyone's phone; the counter rolls to 6/6 and hands off.",
    durationMs: 10_000,
    wide: true,
    render: () => <GroupPhonesScene />,
  },
  {
    key: "mission",
    title: "Mission control",
    caption:
      "The agent's browser and run, the supplier API log, the stay's prebook → book, tickets stacking.",
    durationMs: 12_500,
    wide: true,
    render: () => <MissionControlScene />,
  },
  {
    key: "quick-plan",
    title: "Plan a trip",
    caption:
      "Ask in one line; the agent types, then deals three packages. Take one to choose who pays.",
    durationMs: 6000,
    wide: true,
    render: () => <QuickPlanScene />,
  },
  {
    key: "voice",
    title: "Voice",
    caption:
      "Say it instead: the mic pulses, words stream into the box, silence submits, the agent answers aloud.",
    durationMs: 8000,
    wide: true,
    render: () => <VoiceScene />,
  },
  {
    key: "trust",
    title: "Trust",
    caption:
      "Where every price comes from, links to check it, photos that fail gracefully. Examples never look real.",
    durationMs: 4000,
    render: () => <TrustScene />,
  },
  {
    key: "landing",
    title: "Landing",
    caption: "Headline words rise out of a blur; the chat thread types in and prints a ticket.",
    durationMs: 6000,
    wide: true,
    render: () => <LandingScene />,
  },
  {
    key: "packages",
    title: "Packages arrive",
    caption: "Supplier ticks over shimmering placeholders, then three tickets are dealt.",
    durationMs: 6000,
    render: () => <PackagesScene />,
  },
  {
    key: "voting",
    title: "Voting",
    caption: "Counts roll, the leader glows lime, the winner is stamped, the rest step back.",
    durationMs: 8000,
    render: () => <VotingScene />,
  },
  {
    key: "shares",
    title: "Shares",
    caption: "Badges pop, the bar springs, the last share stamps “6/6 paid” and the stepper moves.",
    durationMs: 7500,
    render: () => <SharesScene />,
  },
  {
    key: "booking",
    title: "Booking",
    caption: "The agent works, the graph lights up, then each booking prints as a ticket.",
    durationMs: DEMO_RAIL_TOTAL_MS / 4 + 4000,
    wide: true,
    render: () => <BookingScene />,
  },
  {
    key: "disruption",
    title: "Disruption",
    caption: "The alert shakes in, the old ticket is stamped “replaced”, shares count up.",
    durationMs: 7000,
    render: () => <DisruptionScene />,
  },
  {
    key: "feed",
    title: "Feed",
    caption:
      "Members slide in from the left, you and the agent from the right; the agent types first.",
    durationMs: 6500,
    render: () => <FeedScene />,
  },
  {
    key: "transitions",
    title: "Page transitions",
    caption: "Pages cross-fade through the View Transitions API; buttons sink when pressed.",
    durationMs: 5000,
    render: () => <TransitionsScene />,
  },
];

/** Advances through the scenes while `playing`; `take` bumps on every (re)start of a scene. */
function usePlayer() {
  const [index, setIndex] = useState(0);
  const [take, setTake] = useState(0);
  const [playing, setPlaying] = useState(true);
  const scene = SCENES[index] ?? SCENES[0];
  const duration = scene?.durationMs ?? 0;

  useEffect(() => {
    if (!playing || index >= SCENES.length - 1) return;
    // `take` is a dependency so a replay restarts the countdown, too.
    void take;
    const timer = window.setTimeout(() => {
      setIndex((value) => value + 1);
      setTake((value) => value + 1);
    }, duration + 600);
    return () => window.clearTimeout(timer);
  }, [playing, index, duration, take]);

  return {
    index,
    take,
    playing,
    select: (next: number) => {
      setIndex(next);
      setTake((value) => value + 1);
      setPlaying(false);
    },
    playAll: () => {
      setIndex(0);
      setTake((value) => value + 1);
      setPlaying(true);
    },
    toggle: () => setPlaying((value) => !value),
  };
}

/** Every animation of the app in sequence, on fake data — rehearse the demo without a backend. */
export function MotionShowcase(): ReactNode {
  const player = usePlayer();
  const reduced = usePrefersReducedMotion();
  const scene = SCENES[player.index];

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 px-4 py-8 sm:px-6 lg:py-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Dev · motion rehearsal</p>
          <h1 className="display mt-3 text-5xl text-ink sm:text-6xl">
            Every <span className="accent-word">moment</span>, in order
          </h1>
          {reduced && (
            <p className="mt-3 text-sm text-warn">
              Reduced motion is on: you are seeing the calm fallbacks.
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={player.playAll}>
            <RotateCcw className="size-4" aria-hidden />
            Play all
          </Button>
          <Button size="sm" variant="outline" onClick={() => player.select(player.index)}>
            <Play className="size-4" aria-hidden />
            Replay scene
          </Button>
          <Button size="sm" variant="ghost" onClick={player.toggle} aria-pressed={!player.playing}>
            <Pause className="size-4" aria-hidden />
            {player.playing ? "Hold on this scene" : "Auto-advance"}
          </Button>
        </div>
      </div>

      <nav aria-label="Scenes" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {SCENES.map((item, index) => (
          <button
            key={item.key}
            type="button"
            onClick={() => player.select(index)}
            aria-current={index === player.index ? "step" : undefined}
            className={cn(
              "ticket-mono shrink-0 rounded-full px-3 py-1.5 text-xs transition duration-150 active:scale-[0.97]",
              index === player.index
                ? "bg-ink text-bg"
                : "bg-surface-sunken text-muted hover:text-ink",
            )}
          >
            {index + 1} · {item.title}
          </button>
        ))}
      </nav>

      {scene && (
        <section aria-labelledby="scene-title" className="space-y-4">
          <div key={`caption-${player.take}`} className="rise-in">
            <h2 id="scene-title" className="text-2xl tracking-[-0.03em] text-ink">
              {player.index + 1}. {scene.title}
            </h2>
            <p className="mt-1 max-w-2xl text-muted">{scene.caption}</p>
          </div>
          {/* A new key per take remounts the scene, so its animations play from the start. */}
          <div key={`${scene.key}-${player.take}`} className={scene.wide ? "" : "max-w-2xl"}>
            {scene.render()}
          </div>
        </section>
      )}
    </div>
  );
}
