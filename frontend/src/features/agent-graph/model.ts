import type { FlowGraph, FlowNode, RunStep, StepSource, StepStatus } from "./schema";

/** The state of a node in the pipeline: its steps folded into one status. */
export type NodeState = {
  status: StepStatus;
  /** Where the decisive step's decision came from; `null` until a step has run. */
  source: StepSource | null;
  durationMs: number;
  /** Iterations finished (loops), counted as distinct `iteration` values of settled steps. */
  iterationsDone: number;
};

const SETTLED: ReadonlySet<StepStatus> = new Set(["done", "healed"]);

/**
 * Folds every step of one node into its status. The latest step decides — a failed attempt
 * followed by a healed one is healed, not failed — except that anything still running wins,
 * because that is what the viewer is watching.
 */
export function nodeStateOf(steps: readonly RunStep[]): NodeState {
  if (steps.length === 0) {
    return { status: "pending", source: null, durationMs: 0, iterationsDone: 0 };
  }
  const ordered = [...steps].sort((a, b) => a.index - b.index);
  const running = ordered.find((step) => step.status === "running");
  const last = ordered[ordered.length - 1] as RunStep;
  const decisive = running ?? last;
  const healed = ordered.some((step) => step.status === "healed");
  const status: StepStatus = decisive.status === "done" && healed ? "healed" : decisive.status;
  return {
    status,
    source: decisive.source,
    durationMs: ordered.reduce((sum, step) => sum + (step.duration_ms ?? 0), 0),
    iterationsDone: settledIterations(ordered).size,
  };
}

function settledIterations(steps: readonly RunStep[]): Set<number> {
  return new Set(
    steps.filter((step) => SETTLED.has(step.status)).map((step) => step.iteration ?? 0),
  );
}

/**
 * A loop's state from its body: an iteration counts once every body node has settled for it,
 * and the loop is done only when every planned iteration is — until then it is running.
 */
export function loopStateOf(
  node: FlowNode,
  ownSteps: readonly RunStep[],
  bodyStepsPerNode: readonly (readonly RunStep[])[],
): NodeState {
  const state = nodeStateOf([...ownSteps, ...bodyStepsPerNode.flat()]);
  const perNode = bodyStepsPerNode.map(settledIterations);
  const [first, ...rest] = perNode;
  const iterationsDone = first
    ? [...first].filter((iteration) => rest.every((set) => set.has(iteration))).length
    : 0;
  const planned = node.iterations ?? 0;
  const unfinished = planned > 0 && iterationsDone < planned && SETTLED.has(state.status);
  return { ...state, status: unfinished ? "running" : state.status, iterationsDone };
}

export function stepsByNode(steps: readonly RunStep[]): Map<string, RunStep[]> {
  const grouped = new Map<string, RunStep[]>();
  for (const step of steps) {
    if (step.node_id === null) continue;
    const list = grouped.get(step.node_id) ?? [];
    list.push(step);
    grouped.set(step.node_id, list);
  }
  return grouped;
}

/**
 * The order the pipeline is drawn in: a topological order of the edges, ties broken by the
 * order of `nodes`. Back edges (a loop returning to its head) cannot be honoured in a line, so
 * when no node is free the earliest remaining one is taken and the cycle is cut there.
 */
export function orderNodes(graph: FlowGraph): FlowNode[] {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const position = new Map(graph.nodes.map((node, index) => [node.id, index]));
  const incoming = new Map<string, Set<string>>(graph.nodes.map((node) => [node.id, new Set()]));
  for (const edge of graph.edges) {
    if (byId.has(edge.from) && byId.has(edge.to) && edge.from !== edge.to) {
      incoming.get(edge.to)?.add(edge.from);
    }
  }
  const remaining = graph.nodes.map((node) => node.id);
  const ordered: FlowNode[] = [];
  while (remaining.length > 0) {
    const free = remaining.find((id) => (incoming.get(id)?.size ?? 0) === 0);
    const next =
      free ?? [...remaining].sort((a, b) => (position.get(a) ?? 0) - (position.get(b) ?? 0))[0];
    if (next === undefined) break;
    remaining.splice(remaining.indexOf(next), 1);
    for (const sources of incoming.values()) sources.delete(next);
    const node = byId.get(next);
    if (node) ordered.push(node);
  }
  return ordered;
}

export type PipelineEntry = {
  node: FlowNode;
  state: NodeState;
  /** Only for loops: the body nodes, each with its own state. */
  body: { node: FlowNode; state: NodeState }[];
};

/** The graph plus the live steps, as the rows the pipeline renders. */
export function buildPipeline(graph: FlowGraph, steps: readonly RunStep[]): PipelineEntry[] {
  const grouped = stepsByNode(steps);
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const inBody = new Set(graph.nodes.flatMap((node) => node.body ?? []));
  return orderNodes(graph)
    .filter((node) => !inBody.has(node.id))
    .map((node) => {
      const own = grouped.get(node.id) ?? [];
      if (node.type !== "loop") return { node, state: nodeStateOf(own), body: [] };
      const body = (node.body ?? [])
        .map((id) => byId.get(id))
        .filter((child): child is FlowNode => child !== undefined)
        .map((child) => ({ node: child, state: nodeStateOf(grouped.get(child.id) ?? []) }));
      const bodySteps = body.map(({ node: child }) => grouped.get(child.id) ?? []);
      return { node, state: loopStateOf(node, own, bodySteps), body };
    });
}

export type RunCounters = {
  llmCalls: number;
  replayed: number;
  rules: number;
  totalMs: number;
};

/** The strip above the graph: how much of the run needed the LLM at all. */
export function countersOf(steps: readonly RunStep[]): RunCounters {
  const settled = steps.filter((step) => step.status !== "pending");
  return {
    llmCalls: settled.filter((step) => step.source === "llm").length,
    replayed: settled.filter((step) => step.source === "flow").length,
    rules: settled.filter((step) => step.source === "rule").length,
    totalMs: settled.reduce((sum, step) => sum + (step.duration_ms ?? 0), 0),
  };
}

/** The chip next to a step: where its decision came from, in a word. */
export const SOURCE_LABEL: Record<StepSource, string> = {
  flow: "replay",
  rule: "rule",
  llm: "AI",
  human: "you",
};

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 10) return `${seconds.toFixed(1)} s`;
  if (seconds < 60) return `${Math.round(seconds)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}
