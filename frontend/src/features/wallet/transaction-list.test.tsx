import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TransactionList, TripPotCard } from "@/features/wallet";
import type { WalletTransactionResponse } from "@/lib/api";

function entry(overrides: Partial<WalletTransactionResponse>): WalletTransactionResponse {
  return {
    id: "t1",
    kind: "top_up",
    amount_minor: 25_000,
    balance_after_minor: 25_000,
    trip_id: null,
    trip_title: null,
    method: "blik",
    status: "completed",
    reference: "BLIK",
    failure_reason: null,
    created_at: "2026-10-31T10:00:00Z",
    completed_at: "2026-10-31T10:00:02Z",
    ...overrides,
  };
}

describe("TransactionList", () => {
  it("signs credits and debits and names the trip", () => {
    render(
      <TransactionList
        currency="PLN"
        transactions={[
          entry({
            id: "t2",
            kind: "share_payment",
            amount_minor: -59_325,
            trip_title: "Weekend in Prague",
          }),
          entry({}),
        ]}
      />,
    );
    expect(screen.getByText("Trip share · Weekend in Prague")).toBeInTheDocument();
    expect(screen.getByText(/^−.*593,25|^−.*593\.25/)).toBeInTheDocument();
    expect(screen.getByText(/^\+.*250/)).toBeInTheDocument();
  });

  it("marks pending and declined top-ups", () => {
    render(
      <TransactionList
        currency="PLN"
        transactions={[entry({ id: "a", status: "pending" }), entry({ id: "b", status: "failed" })]}
      />,
    );
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.getByText("declined")).toBeInTheDocument();
  });

  it("says so when there is nothing yet", () => {
    render(<TransactionList currency="PLN" transactions={[]} />);
    expect(screen.getByText("No transactions yet.")).toBeInTheDocument();
  });
});

describe("TripPotCard", () => {
  it("shows what the trip escrow holds and who holds it", () => {
    render(
      <TripPotCard
        currency="PLN"
        pot={{
          collected_minor: 355_950,
          spent_minor: 330_556,
          refunded_minor: 25_394,
          held_minor: 0,
          pay_by: "2099-01-01T12:00:00Z",
        }}
      />,
    );
    expect(screen.getByText("Trip escrow")).toBeInTheDocument();
    expect(screen.getByText("Paid to suppliers")).toBeInTheDocument();
    expect(screen.getByText(/simulated licensed partner/)).toBeInTheDocument();
    expect(screen.getByText(/goes back automatically/)).toBeInTheDocument();
  });
});
