import { describe, expect, it } from "vitest";

import { DEMO_RAIL_GRAPH, DEMO_RAIL_STEPS, DEMO_RAIL_TOTAL_MS, stepsAt } from "./fixtures";
import { buildPipeline, countersOf, nodeStateOf, orderNodes } from "./model";
import { countersSentence } from "./run-counters";
import { parseFlowGraph, parseRunSteps, type RunStep } from "./schema";

function step(overrides: Partial<RunStep>): RunStep {
  return {
    index: 0,
    node_id: "n",
    kind: "click",
    status: "done",
    duration_ms: 1000,
    source: "flow",
    ...overrides,
  };
}

describe("parseFlowGraph", () => {
  it("accepts the fixture and keeps unknown node types as 'other'", () => {
    const result = parseFlowGraph({
      nodes: [...DEMO_RAIL_GRAPH.nodes, { id: "x", type: "teleport", label: "Teleport" }],
      edges: DEMO_RAIL_GRAPH.edges,
    });
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value.nodes.at(-1)?.type).toBe("other");
  });

  it("defaults missing edges and rejects a node without an id", () => {
    const ok = parseFlowGraph({ nodes: [{ id: "a", type: "click", label: "A" }] });
    expect(ok.ok && ok.value.edges).toEqual([]);
    expect(parseFlowGraph({ nodes: [{ type: "click", label: "A" }] }).ok).toBe(false);
  });
});

describe("parseRunSteps", () => {
  it("refuses a status the UI cannot show honestly", () => {
    const result = parseRunSteps([{ index: 0, node_id: "a", status: "exploded", source: "flow" }]);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain("status");
  });

  it("fills defaults for optional fields", () => {
    const result = parseRunSteps([{ index: 0, status: "running", source: "llm" }]);
    expect(result.ok && result.value[0]).toMatchObject({
      node_id: null,
      duration_ms: null,
      kind: "other",
    });
  });
});

describe("nodeStateOf", () => {
  it("is pending without steps", () => {
    expect(nodeStateOf([]).status).toBe("pending");
  });

  it("lets a running step win and the latest step decide otherwise", () => {
    expect(
      nodeStateOf([step({ status: "done" }), step({ index: 1, status: "running" })]).status,
    ).toBe("running");
    expect(
      nodeStateOf([step({ status: "failed" }), step({ index: 1, status: "done" })]).status,
    ).toBe("done");
    expect(
      nodeStateOf([step({ status: "done" }), step({ index: 1, status: "failed" })]).status,
    ).toBe("failed");
  });

  it("reports a node that needed healing as healed, with the healer as its source", () => {
    const state = nodeStateOf([
      step({ status: "healed", source: "llm" }),
      step({ index: 1, status: "done", source: "llm" }),
    ]);
    expect(state).toMatchObject({ status: "healed", source: "llm", durationMs: 2000 });
  });
});

describe("orderNodes", () => {
  it("follows the edges, cutting the loop's back edge", () => {
    expect(orderNodes(DEMO_RAIL_GRAPH).map((node) => node.id)).toEqual(
      DEMO_RAIL_GRAPH.nodes.map((node) => node.id),
    );
  });

  it("follows edges even when the nodes are listed out of order", () => {
    const graph = {
      nodes: [
        { id: "b", type: "click" as const, label: "B" },
        { id: "a", type: "open_url" as const, label: "A" },
      ],
      edges: [{ from: "a", to: "b" }],
    };
    expect(orderNodes(graph).map((node) => node.id)).toEqual(["a", "b"]);
  });
});

describe("buildPipeline", () => {
  it("nests the loop body and keeps the loop running until every iteration is done", () => {
    const twoOfThree = DEMO_RAIL_STEPS.slice(0, 4);
    const loop = buildPipeline(DEMO_RAIL_GRAPH, twoOfThree).find(
      (entry) => entry.node.id === "passengers",
    );
    expect(loop?.body.map((child) => child.node.id)).toEqual(["passenger_details"]);
    expect(loop?.state).toMatchObject({ status: "running", iterationsDone: 2 });

    const all = buildPipeline(DEMO_RAIL_GRAPH, DEMO_RAIL_STEPS);
    expect(all.map((entry) => entry.node.id)).not.toContain("passenger_details");
    expect(all.find((entry) => entry.node.id === "passengers")?.state.status).toBe("done");
  });
});

describe("countersOf", () => {
  it("counts where decisions came from: 1 LLM call, 6 replayed, 2 rules, 27 s", () => {
    const counters = countersOf(DEMO_RAIL_STEPS);
    expect(counters).toEqual({ llmCalls: 1, replayed: 6, rules: 2, totalMs: 27_000 });
    expect(countersSentence(counters)).toBe("LLM calls: 1 · replayed: 6 · rules: 2 · 27 s");
  });
});

describe("stepsAt", () => {
  it("shows nothing finished at the start and everything at the end", () => {
    expect(stepsAt(DEMO_RAIL_STEPS, 0)).toEqual([
      { ...DEMO_RAIL_STEPS[0], status: "running", duration_ms: 0 },
    ]);
    expect(stepsAt(DEMO_RAIL_STEPS, DEMO_RAIL_TOTAL_MS)).toEqual(DEMO_RAIL_STEPS);
  });

  it("reports the current step as running with the time spent so far", () => {
    const steps = stepsAt(DEMO_RAIL_STEPS, 3000);
    expect(steps).toHaveLength(2);
    expect(steps[1]).toMatchObject({
      node_id: "choose_train",
      status: "running",
      duration_ms: 900,
    });
  });
});
