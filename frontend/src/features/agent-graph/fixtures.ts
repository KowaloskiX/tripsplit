import type { FlowGraph, RunStep } from "./schema";

/**
 * A realistic purchase on the demo rail supplier: three passengers on EC 131 Warszawa → Praha.
 * Shaped exactly like `flow_graph.json` + `status.json` steps, so the dev route can show the
 * graph without a backend and the tests have something true to chew on.
 */
export const DEMO_RAIL_GRAPH: FlowGraph = {
  nodes: [
    {
      id: "open_results",
      type: "open_url",
      label: "Open the search results",
      inputs: ["origin", "destination", "date"],
    },
    {
      id: "choose_train",
      type: "choose",
      label: "Choose EC 131 Warszawa → Praha",
      inputs: ["train"],
    },
    {
      id: "passengers",
      type: "loop",
      label: "Fill in the passengers",
      body: ["passenger_details"],
      iterations: 3,
      iteration_label: "passenger",
    },
    {
      id: "passenger_details",
      type: "fill",
      label: "Passenger details",
      inputs: ["passenger_N_first_name", "passenger_N_last_name"],
    },
    { id: "contact_email", type: "fill", label: "Contact email", inputs: ["email"] },
    { id: "to_summary", type: "click", label: "Continue to the summary" },
    {
      id: "verify_summary",
      type: "verify",
      label: "Verify the summary",
      inputs: ["passengers", "total"],
    },
    { id: "approve", type: "approve", label: "Organizer approves the payment" },
  ],
  edges: [
    { from: "open_results", to: "choose_train" },
    { from: "choose_train", to: "passengers" },
    { from: "passengers", to: "passenger_details" },
    { from: "passenger_details", to: "passengers" },
    { from: "passengers", to: "contact_email" },
    { from: "contact_email", to: "to_summary" },
    { from: "to_summary", to: "verify_summary" },
    { from: "verify_summary", to: "approve" },
  ],
};

/** The finished run: 1 LLM call (it healed a changed results page), 6 replayed, 2 rules, 27 s. */
export const DEMO_RAIL_STEPS: RunStep[] = [
  {
    index: 0,
    node_id: "open_results",
    kind: "open_url",
    status: "done",
    duration_ms: 2100,
    source: "flow",
  },
  {
    index: 1,
    node_id: "choose_train",
    kind: "choose",
    status: "healed",
    duration_ms: 6800,
    source: "llm",
  },
  {
    index: 2,
    node_id: "passenger_details",
    kind: "fill",
    status: "done",
    duration_ms: 2400,
    source: "flow",
    iteration: 0,
  },
  {
    index: 3,
    node_id: "passenger_details",
    kind: "fill",
    status: "done",
    duration_ms: 2200,
    source: "flow",
    iteration: 1,
  },
  {
    index: 4,
    node_id: "passenger_details",
    kind: "fill",
    status: "done",
    duration_ms: 2300,
    source: "flow",
    iteration: 2,
  },
  {
    index: 5,
    node_id: "contact_email",
    kind: "fill",
    status: "done",
    duration_ms: 1600,
    source: "flow",
  },
  {
    index: 6,
    node_id: "to_summary",
    kind: "click",
    status: "done",
    duration_ms: 1900,
    source: "flow",
  },
  {
    index: 7,
    node_id: "verify_summary",
    kind: "verify",
    status: "done",
    duration_ms: 3200,
    source: "rule",
  },
  {
    index: 8,
    node_id: "approve",
    kind: "approve",
    status: "done",
    duration_ms: 4500,
    source: "rule",
  },
];

export const DEMO_RAIL_TOTAL_MS = DEMO_RAIL_STEPS.reduce(
  (sum, step) => sum + (step.duration_ms ?? 0),
  0,
);

/**
 * The run as it looked `elapsedMs` after it started: finished steps as recorded, the current
 * one `running` with the time spent so far, later ones not reported yet — exactly what a
 * polled `status.json` would show.
 */
export function stepsAt(steps: readonly RunStep[], elapsedMs: number): RunStep[] {
  const visible: RunStep[] = [];
  let startedAt = 0;
  for (const step of steps) {
    if (elapsedMs < startedAt) break;
    const duration = step.duration_ms ?? 0;
    const spent = elapsedMs - startedAt;
    visible.push(spent >= duration ? step : { ...step, status: "running", duration_ms: spent });
    startedAt += duration;
  }
  return visible;
}
