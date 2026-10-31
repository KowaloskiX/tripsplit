import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ProposalResponse } from "@/lib/api";

import { ProposalCard } from "./proposal-card";

const PROPOSAL: ProposalResponse = {
  id: "p1",
  title: "Budget: PKP Intercity EC + hostel",
  summary: "",
  items: [],
  total_minor: 355_950,
  per_person_minor: 59_325,
  over_budget: false,
  votes: 0,
  voted_by_me: false,
  chosen: false,
};

describe("ProposalCard", () => {
  it("flags a package that costs more per person than the budget", () => {
    render(<ProposalCard proposal={{ ...PROPOSAL, over_budget: true }} currency="PLN" />);
    expect(screen.getByText("over budget")).toBeInTheDocument();
  });

  it("shows no budget badge for a package that fits", () => {
    render(<ProposalCard proposal={PROPOSAL} currency="PLN" />);
    expect(screen.queryByText("over budget")).not.toBeInTheDocument();
  });
});
