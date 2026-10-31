import { type ReactNode, useMemo } from "react";

import { AgentRunGraph, parseFlowGraph, parseRunSteps } from "@/features/agent-graph";
import type { RunStepResponse } from "@/lib/api";

import { useRunGraph } from "./queries";

type RunGraphProps = {
  runId: string;
  /** The run is working: the plan is polled until the agent has written it. */
  active: boolean;
  /** `status.json` steps from the run status (polled every second by the caller). */
  steps: readonly RunStepResponse[] | undefined;
  title?: string;
};

/** The agent's plan lit up by what it has done so far — nothing until the plan exists. */
export function RunGraph({ runId, active, steps, title }: RunGraphProps): ReactNode {
  const graph = useRunGraph(runId, active);
  const parsedGraph = useMemo(() => (graph.data ? parseFlowGraph(graph.data) : null), [graph.data]);
  const parsedSteps = useMemo(
    // The API sends `iteration: null` for a step outside a loop; the graph wants it absent.
    () =>
      parseRunSteps(
        (steps ?? []).map(({ iteration, ...step }) =>
          iteration === null ? step : { ...step, iteration },
        ),
      ),
    [steps],
  );
  if (!parsedGraph?.ok) return null;
  return (
    <AgentRunGraph
      graph={parsedGraph.value}
      steps={parsedSteps.ok ? parsedSteps.value : []}
      {...(title ? { title } : {})}
    />
  );
}
