import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BookingStage } from "./booking-stage";
import type { MissionControlData } from "./model";

const MISSION: MissionControlData = {
  title: "Booking Prague",
  currency: "PLN",
  purchases: 2,
  browser: { host: "www.intercity.pl", steps: [{ id: "a", label: "Open", status: "running" }] },
  calls: [
    { at: "2026-11-20T12:00:00Z", method: "POST", path: "/air/orders", status: 201, ms: 412 },
  ],
  stay: null,
  tickets: [],
};

describe("BookingStage", () => {
  it("renders only the regular booking UI without mission data", () => {
    render(
      <BookingStage>
        <p>bookings list</p>
      </BookingStage>,
    );
    expect(screen.getByText("bookings list")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Mission control" })).not.toBeInTheDocument();
  });

  it("puts mission control above the bookings when data is there", () => {
    render(
      <BookingStage mission={MISSION}>
        <p>bookings list</p>
      </BookingStage>,
    );
    expect(screen.getByRole("region", { name: "Mission control" })).toBeInTheDocument();
    expect(screen.getByText("/air/orders")).toBeInTheDocument();
    expect(screen.getByText("0 of 2 purchases done")).toBeInTheDocument();
    expect(screen.getByText("bookings list")).toBeInTheDocument();
  });
});
