import { BadgeCheck, Clock, type LucideIcon, Repeat, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { type RunCounters as Counters, formatDuration } from "./model";

type Tile = { label: string; value: string; icon: LucideIcon; tone: string };

/** "LLM calls: 1 · replayed: 6 · rules: 2 · 27 s" — the counter strip as one sentence. */
export function countersSentence(counters: Counters): string {
  return `LLM calls: ${counters.llmCalls} · replayed: ${counters.replayed} · rules: ${counters.rules} · ${formatDuration(counters.totalMs)}`;
}

/** How much of the run needed the LLM — the point of flows and rules, made visible. */
export function RunCounters({ counters }: { counters: Counters }): ReactNode {
  const tiles: Tile[] = [
    {
      label: "AI calls",
      value: String(counters.llmCalls),
      icon: Sparkles,
      tone: "bg-pastel-blush text-pastel-ink",
    },
    {
      label: "Replayed",
      value: String(counters.replayed),
      icon: Repeat,
      tone: "bg-pastel-sky text-pastel-ink",
    },
    {
      label: "Rules",
      value: String(counters.rules),
      icon: BadgeCheck,
      tone: "bg-surface-sunken text-muted",
    },
    {
      label: "Time",
      value: formatDuration(counters.totalMs),
      icon: Clock,
      tone: "bg-lime text-pastel-ink",
    },
  ];
  return (
    <dl aria-label={countersSentence(counters)} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {tiles.map((tile) => (
        <div
          key={tile.label}
          className="flex items-center gap-3 rounded-[24px] bg-surface-sunken px-3.5 py-3"
        >
          <span
            className={cn(
              "inline-flex size-9 shrink-0 items-center justify-center rounded-full",
              tile.tone,
            )}
          >
            <tile.icon className="size-[18px]" aria-hidden />
          </span>
          <div className="min-w-0">
            <dt className="whitespace-nowrap text-xs font-medium text-muted">{tile.label}</dt>
            <dd className="ticket-mono whitespace-nowrap text-xl leading-tight text-ink">
              {tile.value}
            </dd>
          </div>
        </div>
      ))}
    </dl>
  );
}
