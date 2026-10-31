import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ContributionsTable } from "@/features/contributions";
import type { ContributionResponse } from "@/lib/api";

function share(userId: string, name: string, paid: boolean): ContributionResponse {
  return {
    user_id: userId,
    display_name: name,
    amount_minor: 50_000,
    paid_minor: paid ? 50_000 : 0,
    outstanding_minor: paid ? 0 : 50_000,
    refund_minor: 0,
    status: paid ? "paid" : "pending",
  };
}

const NAMES = ["Łukasz", "Ola", "Kuba", "Marta", "Bartek", "Zosia"];

describe("ContributionsTable", () => {
  it("shows how many of the group have paid", () => {
    const contributions = NAMES.map((name, index) => share(`u${index}`, name, index < 4));
    render(<ContributionsTable contributions={contributions} currency="PLN" myUserId="u0" />);

    expect(screen.getByText("4/6 paid")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "4 of 6 shares paid" });
    expect(bar).toHaveAttribute("aria-valuenow", "4");
    expect(bar).toHaveAttribute("aria-valuemax", "6");
  });

  it("marks each member's status and the current user", () => {
    const contributions = [share("u0", "Łukasz", true), share("u1", "Ola", false)];
    render(<ContributionsTable contributions={contributions} currency="PLN" myUserId="u0" />);

    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0] as HTMLElement).getByText("paid")).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText("(you)")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("pending")).toBeInTheDocument();
  });

  it("shows a refund and leaves a former member's settled share out of the progress", () => {
    const leaver: ContributionResponse = {
      ...share("u2", "Kuba", true),
      amount_minor: 0,
      refund_minor: 50_000,
      status: "refund_due",
    };
    const contributions = [share("u0", "Łukasz", true), share("u1", "Ola", false), leaver];
    render(<ContributionsTable contributions={contributions} currency="PLN" myUserId="u0" />);

    expect(screen.getByText("1/2 paid")).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[2] as HTMLElement).getByText(/^refund /)).toBeInTheDocument();
  });

  it("shows the exact amount paid, grosze included, once everyone paid", () => {
    const contributions = NAMES.map((name, index) => ({
      ...share(`u${index}`, name, true),
      amount_minor: 74_039,
      paid_minor: 74_039,
    }));
    render(<ContributionsTable contributions={contributions} currency="PLN" myUserId="u0" />);

    expect(screen.getAllByText(/4\s442\.34\sPLN/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/4\s442\.00/)).not.toBeInTheDocument();
  });
});
