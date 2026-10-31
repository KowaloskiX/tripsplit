import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BookingStatus } from "@/lib/api";

import { BOOKING_STATUS_META, BookingStatusBadge } from "./booking-status-badge";

const ALL_STATUSES: readonly BookingStatus[] = [
  "pending",
  "running",
  "awaiting_approval",
  "approved",
  "confirmed",
  "handoff",
  "failed",
  "cancelled",
];

describe("BookingStatusBadge", () => {
  it.each([
    ["pending", "Not started", "neutral"],
    ["running", "Agent working", "live"],
    ["awaiting_approval", "Needs approval", "attention"],
    ["approved", "Paying", "live"],
    ["confirmed", "Confirmed", "success"],
    ["handoff", "Needs a human", "attention"],
    ["failed", "Failed", "danger"],
    ["cancelled", "Replaced", "muted"],
  ] as const)("shows %s as %s", (status, label, tone) => {
    render(<BookingStatusBadge status={status} />);
    const badge = screen.getByText(label);
    expect(badge).toHaveAttribute("data-tone", tone);
  });

  it("has a distinct label for every status", () => {
    const labels = ALL_STATUSES.map((status) => BOOKING_STATUS_META[status].label);
    expect(new Set(labels).size).toBe(ALL_STATUSES.length);
  });
});
