import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MemberResponse } from "@/lib/api";

import { toTravellerDetailsBody, travellerDetailsSchema } from "./schema";
import { TravellerChecklist } from "./traveller-checklist";

const MEMBERS: MemberResponse[] = [
  {
    user_id: "u1",
    display_name: "Anna Kowalska",
    role: "organizer",
    traveller_details_missing: [],
    traveller_details_complete: true,
  },
  {
    user_id: "u2",
    display_name: "Kuba Mazur",
    role: "member",
    traveller_details_missing: ["date_of_birth", "document_number"],
    traveller_details_complete: false,
  },
];

describe("TravellerChecklist", () => {
  it("names who is missing which fields — no values", () => {
    render(<TravellerChecklist members={MEMBERS} />);
    expect(screen.getByText("details complete")).toBeInTheDocument();
    expect(screen.getByText("missing: date of birth, document number")).toBeInTheDocument();
  });
});

describe("travellerDetailsSchema", () => {
  it("sends only what was typed; empty keeps the stored value", () => {
    const values = travellerDetailsSchema.parse({
      fullName: "",
      dateOfBirth: "1990-05-01",
      nationality: "pl",
      documentNumber: "",
      documentExpiry: "",
    });
    expect(toTravellerDetailsBody(values)).toEqual({
      full_name: null,
      date_of_birth: "1990-05-01",
      nationality: "PL",
      document_number: null,
      document_expiry: null,
    });
  });

  it("rejects a single name and a three-letter country", () => {
    const parsed = travellerDetailsSchema.safeParse({
      fullName: "Anna",
      dateOfBirth: "",
      nationality: "POL",
      documentNumber: "",
      documentExpiry: "",
    });
    expect(parsed.success).toBe(false);
  });
});
