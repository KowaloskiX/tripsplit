import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ItineraryDayResponse } from "@/lib/api";

import { ItineraryView } from "./itinerary-view";

const item = (over: Partial<ItineraryDayResponse["items"][number]>) => ({
  start: "10:00",
  end: "11:30",
  kind: "attraction" as const,
  title: "Prague Castle",
  place: "",
  lat: 50.09,
  lon: 14.4,
  link: "",
  map_url: "https://www.openstreetmap.org/?mlat=50.09&mlon=14.4#map=17",
  note: "",
  attraction_id: "a1",
  tickets: null,
  booking_id: null,
  ...over,
});

const DAYS: ItineraryDayResponse[] = [
  {
    date: "2026-11-21",
    label: "Saturday",
    items: [
      item({ kind: "travel", title: "Walk to Prague Castle", map_url: "", attraction_id: null }),
      item({}),
      item({ start: "13:00", end: "14:00", kind: "meal", title: "Lunch", attraction_id: null }),
      item({ start: "15:00", end: "17:30", title: "National Museum", tickets: "booked" }),
    ],
  },
];

describe("ItineraryView", () => {
  it("renders a day with its time rail, map links and a tickets-booked badge", () => {
    render(<ItineraryView days={DAYS} />);
    const day = screen.getByRole("region", { name: "Saturday plan" });
    expect(within(day).getAllByRole("listitem")).toHaveLength(4);
    expect(within(day).getByText("tickets booked")).toBeInTheDocument();
    expect(within(day).getAllByRole("link", { name: /Map/ }).length).toBeGreaterThan(0);
    expect(within(day).getByText("15:00")).toBeInTheDocument();
  });
});
