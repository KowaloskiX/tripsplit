import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentRunGraph } from "./agent-run-graph";
import { DEMO_RAIL_GRAPH, DEMO_RAIL_STEPS, stepsAt } from "./fixtures";

describe("AgentRunGraph", () => {
  it("lights up the node being worked on and leaves the rest waiting", () => {
    const { container } = render(
      <AgentRunGraph graph={DEMO_RAIL_GRAPH} steps={stepsAt(DEMO_RAIL_STEPS, 3000)} />,
    );
    const status = (id: string) =>
      container.querySelector(`li[data-node-id="${id}"]`)?.getAttribute("data-status");
    expect(status("open_results")).toBe("done");
    expect(status("choose_train")).toBe("running");
    expect(status("approve")).toBe("pending");
    expect(screen.getByText("Agent working")).toBeInTheDocument();
  });

  it("shows the loop's iterations and the counter strip of a finished run", () => {
    render(<AgentRunGraph graph={DEMO_RAIL_GRAPH} steps={DEMO_RAIL_STEPS} />);
    expect(screen.getByText("× 3 passengers")).toBeInTheDocument();
    expect(
      screen.getByLabelText("LLM calls: 1 · replayed: 6 · rules: 2 · 27 s"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Run complete")).not.toHaveLength(0);
  });
});
