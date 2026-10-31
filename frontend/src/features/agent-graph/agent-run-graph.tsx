import { type ReactNode, useMemo } from "react";

import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";

import { buildPipeline, countersOf, type PipelineEntry } from "./model";
import { LoopBody, PipelineNode } from "./pipeline-node";
import { RunCounters } from "./run-counters";
import type { FlowGraph, RunStep, StepStatus } from "./schema";

export type RunPhase = "waiting" | "running" | "done" | "failed";

/** The whole run in one word, from its rows. */
export function runPhaseOf(entries: readonly PipelineEntry[]): RunPhase {
  const statuses = entries.map((entry) => entry.state.status);
  if (statuses.includes("failed")) return "failed";
  if (statuses.length > 0 && statuses.every((status) => status === "done" || status === "healed")) {
    return "done";
  }
  return statuses.some((status) => status !== "pending") ? "running" : "waiting";
}

const PHASE: Record<RunPhase, { label: string; tone: BadgeTone }> = {
  waiting: { label: "Not started", tone: "outline" },
  running: { label: "Agent working", tone: "lime" },
  done: { label: "Run complete", tone: "success" },
  failed: { label: "Needs attention", tone: "danger" },
};

const LIVE_STATUSES: ReadonlySet<StepStatus> = new Set(["running"]);

type AgentRunGraphProps = {
  /** The plan: `runs/<id>/flow_graph.json`, parsed with `parseFlowGraph`. */
  graph: FlowGraph;
  /** What has happened: `status.json` `steps`, parsed with `parseRunSteps`. Poll and pass in. */
  steps: readonly RunStep[];
  /** e.g. "EC 131 Warszawa → Praha · 3 passengers". */
  title?: string;
};

/**
 * The purchase run as a live pipeline: every node of the flow graph lights up as the agent
 * reaches it, with where each decision came from (replayed flow, rule or the LLM) and how long
 * it took. Presentational — the caller owns fetching and polling.
 */
export function AgentRunGraph({ graph, steps, title }: AgentRunGraphProps): ReactNode {
  const entries = useMemo(() => buildPipeline(graph, steps), [graph, steps]);
  const counters = useMemo(() => countersOf(steps), [steps]);
  const phase = PHASE[runPhaseOf(entries)];
  const current = entries.find((entry) => LIVE_STATUSES.has(entry.state.status));

  return (
    <Panel className="space-y-5 p-4 sm:p-6" role="region" aria-label="Agent run">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow">Live purchase</p>
          {title && <h2 className="mt-2 text-2xl tracking-[-0.03em] text-ink">{title}</h2>}
        </div>
        <Badge tone={phase.tone} pulse={phase.label === PHASE.running.label}>
          {phase.label}
        </Badge>
      </div>

      <RunCounters counters={counters} />

      {/* Announces the step being worked on; the rows themselves stay quiet. */}
      <p className="sr-only" aria-live="polite">
        {current ? `Now: ${current.node.label}` : phase.label}
      </p>

      <ol aria-label="Steps of the purchase" className="pt-1">
        {entries.map((entry, index) => (
          <PipelineNode
            key={entry.node.id}
            node={entry.node}
            state={entry.state}
            last={index === entries.length - 1}
          >
            {entry.node.type === "loop" && (
              <LoopBody node={entry.node} state={entry.state} body={entry.body} />
            )}
          </PipelineNode>
        ))}
      </ol>
    </Panel>
  );
}
