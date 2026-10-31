/** Public surface of the agent-graph feature — the live purchase run as a pipeline. */
export { AgentRunGraph, type RunPhase, runPhaseOf } from "./agent-run-graph";
export { DEMO_RAIL_GRAPH, DEMO_RAIL_STEPS, DEMO_RAIL_TOTAL_MS, stepsAt } from "./fixtures";
export { buildPipeline, countersOf, type NodeState, type RunCounters } from "./model";
export { countersSentence } from "./run-counters";
export {
  type FlowEdge,
  type FlowGraph,
  type FlowNode,
  type FlowNodeType,
  type ParseResult,
  parseFlowGraph,
  parseRunSteps,
  type RunStep,
  type StepSource,
  type StepStatus,
} from "./schema";
