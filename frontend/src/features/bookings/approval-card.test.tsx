import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApprovalCard } from "./approval-card";

function renderCard(overrides: Partial<Parameters<typeof ApprovalCard>[0]> = {}) {
  const onDecision = vi.fn();
  render(
    <ApprovalCard
      frameUrl="/api/agent-runs/b1-1/frame?t=1"
      supplier="PKP Intercity"
      amountMinor={124_000}
      currency="PLN"
      travellers={6}
      pending={false}
      onDecision={onDecision}
      {...overrides}
    />,
  );
  return { onDecision };
}

describe("ApprovalCard", () => {
  it("shows the summary screenshot and the amount", () => {
    renderCard();
    expect(screen.getByRole("img", { name: "Summary page on PKP Intercity" })).toHaveAttribute(
      "src",
      "/api/agent-runs/b1-1/frame?t=1",
    );
    expect(screen.getByText(/1 240\.00 PLN/)).toHaveTextContent("1 240.00 PLN budgeted");
    expect(screen.getByText(/For 6 people\./)).toBeInTheDocument();
  });

  it("approves and rejects", async () => {
    const user = userEvent.setup();
    const { onDecision } = renderCard();
    await user.click(screen.getByRole("button", { name: "Approve and pay" }));
    await user.click(screen.getByRole("button", { name: "Reject" }));
    expect(onDecision.mock.calls).toEqual([[true], [false]]);
  });

  it("locks both buttons while the decision is being sent", () => {
    renderCard({ pending: true });
    expect(screen.getByRole("button", { name: /Approve/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });
});
