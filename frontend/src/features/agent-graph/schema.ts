import { z } from "zod";

/**
 * The booking agent's run, as it is written to disk: `runs/<id>/flow_graph.json` (the plan)
 * and the `steps` of `status.json` (what has happened so far).
 *
 * The API does not expose these yet, so they are validated here, at the boundary. Parsing is
 * lenient where the agent is likely to grow (a new node type or step kind becomes `"other"`
 * instead of failing the whole graph) and strict where the UI would lie (an unknown status).
 */

export const NODE_TYPES = [
  "open_url",
  "fill",
  "choose",
  "click",
  "loop",
  "verify",
  "approve",
  "extract",
  "wait",
  "other",
] as const;
export type FlowNodeType = (typeof NODE_TYPES)[number];

export const STEP_STATUSES = ["pending", "running", "done", "failed", "healed"] as const;
export type StepStatus = (typeof STEP_STATUSES)[number];

/** Where a step's decision came from: a recorded flow replayed, a rule, or the LLM planner. */
export const STEP_SOURCES = ["flow", "rule", "llm"] as const;
export type StepSource = (typeof STEP_SOURCES)[number];

const nodeType = z.enum(NODE_TYPES).catch("other");

const flowNodeSchema = z.object({
  id: z.string().min(1),
  type: nodeType,
  label: z.string(),
  /** Vault keys or field names the node reads — names only, never values. */
  inputs: z.array(z.string()).optional(),
  /** A loop's body: the ids of the nodes it repeats, in order. */
  body: z.array(z.string()).optional(),
  /** A loop's planned number of iterations ("× 3 passengers"). */
  iterations: z.number().int().nonnegative().optional(),
  /** What one iteration is, singular ("passenger"). */
  iteration_label: z.string().optional(),
});

const flowEdgeSchema = z.object({ from: z.string(), to: z.string() });

export const flowGraphSchema = z.object({
  nodes: z.array(flowNodeSchema),
  edges: z.array(flowEdgeSchema).default([]),
});

export const runStepSchema = z.object({
  index: z.number().int().nonnegative(),
  node_id: z.string().nullable().default(null),
  kind: nodeType.default("other"),
  status: z.enum(STEP_STATUSES),
  duration_ms: z.number().nonnegative().nullable().default(null),
  source: z.enum(STEP_SOURCES),
  /** Which loop iteration this step belongs to, 0-based. */
  iteration: z.number().int().nonnegative().optional(),
});

export const runStepsSchema = z.array(runStepSchema);

export type FlowNode = z.infer<typeof flowNodeSchema>;
export type FlowEdge = z.infer<typeof flowEdgeSchema>;
export type FlowGraph = z.infer<typeof flowGraphSchema>;
export type RunStep = z.infer<typeof runStepSchema>;

export type ParseResult<T> = { ok: true; value: T } | { ok: false; error: string };

function toResult<T>(parsed: z.ZodSafeParseResult<T>): ParseResult<T> {
  return parsed.success
    ? { ok: true, value: parsed.data }
    : { ok: false, error: z.prettifyError(parsed.error) };
}

/** `flow_graph.json` -> a graph, or a readable reason it is not one. */
export function parseFlowGraph(input: unknown): ParseResult<FlowGraph> {
  return toResult(flowGraphSchema.safeParse(input));
}

/** The `steps` array of `status.json` -> steps, or a readable reason. */
export function parseRunSteps(input: unknown): ParseResult<RunStep[]> {
  return toResult(runStepsSchema.safeParse(input));
}
