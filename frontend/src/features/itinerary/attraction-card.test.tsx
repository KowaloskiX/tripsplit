import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AttractionResponse } from "@/lib/api";

import { AttractionCard, attractionProvenance, priceLabel } from "./attraction-card";

const MUSEUM: AttractionResponse = {
  attraction_id: "a1",
  title: "National Museum",
  kind: "museum",
  image_url: "",
  website: "https://www.nm.cz/en",
  lat: 50.079,
  lon: 14.43,
  opens: "10:00",
  closes: "18:00",
  duration_minutes: 150,
  price_per_person_minor: 7000,
  currency: "PLN",
  bookable: true,
  provenance: "Demo ticket shop",
  rank: 1,
  votes: 2,
  voters: [
    { user_id: "u1", display_name: "Ola Sikora" },
    { user_id: "u2", display_name: "Kuba Mazur" },
  ],
  voted_by_me: false,
};

describe("AttractionCard", () => {
  it("shows the kind, the price, the voters and toggles the vote", () => {
    const onToggle = vi.fn();
    render(<AttractionCard attraction={MUSEUM} majority={3} onToggle={onToggle} />);
    expect(screen.getByText("Museum")).toBeInTheDocument();
    expect(screen.getByText(/agent buys tickets/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Ola Sikora, Kuba Mazur" })).toBeInTheDocument();
    expect(screen.queryByText("in the plan")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "I want this" }));
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("marks what half the group wants and hides the toggle when voting is over", () => {
    render(<AttractionCard attraction={{ ...MUSEUM, votes: 3 }} majority={3} />);
    expect(screen.getByText("in the plan")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("says free for an idea without a price and reads provenance", () => {
    expect(priceLabel({ ...MUSEUM, price_per_person_minor: null })).toBe("Free / pay on site");
    expect(attractionProvenance("live")).toEqual({ kind: "live", source: "Wikipedia" });
    expect(attractionProvenance("Demo ticket shop")?.kind).toBe("test");
    expect(attractionProvenance("")).toBeUndefined();
  });
});
