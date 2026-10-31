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

  it("shows the transport segments generically, whatever the mode", () => {
    const flight = {
      kind: "transport" as const,
      mode: "flight" as const,
      title: "Ryanair FR 2659 WMI -> BCN (return)",
      supplier: "Ryanair",
      supplier_url: "https://sim.tripsplit.invalid/x",
      price_minor: 410_400,
      details: "",
      starts_at: null,
      segments: [
        {
          carrier: "Ryanair",
          number: "FR 2659",
          origin: "WMI",
          destination: "BCN",
          departs_at: "2026-11-20T06:25:00+01:00",
          arrives_at: "2026-11-20T09:50:00+01:00",
        },
      ],
    };
    render(<ProposalCard proposal={{ ...PROPOSAL, items: [flight] }} currency="PLN" />);
    expect(screen.getByRole("img", { name: "Flight" })).toBeInTheDocument();
    expect(screen.getByText(/FR 2659 WMI → BCN/)).toBeInTheDocument();
  });

  it("shows no budget badge for a package that fits", () => {
    render(<ProposalCard proposal={PROPOSAL} currency="PLN" />);
    expect(screen.queryByText("over budget")).not.toBeInTheDocument();
  });
});
