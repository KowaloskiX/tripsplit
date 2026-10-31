import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { owesTopUp, StatusStepper, stepsFor } from "./status-stepper";

describe("StatusStepper", () => {
  it("marks earlier stages done and the current one as the step", () => {
    render(<StatusStepper status="paying" />);
    const list = screen.getByRole("list", { name: "Trip progress" });
    const items = Array.from(list.querySelectorAll("li"));
    expect(items.map((item) => item.dataset.state)).toEqual([
      "done",
      "done",
      "current",
      "upcoming",
      "upcoming",
    ]);
    expect(items[2]).toHaveAttribute("aria-current", "step");
    expect(items[2]).toHaveTextContent("Paying");
  });

  it("highlights a disruption on the booking stage under its own name", () => {
    const steps = stepsFor("rebooking");
    expect(steps[3]).toMatchObject({ state: "alert", label: "Rebooking" });
    expect(steps[4]?.state).toBe("upcoming");
    expect(stepsFor("disrupted")[3]?.label).toBe("Disrupted");
  });

  it("shows a booked trip as complete", () => {
    expect(stepsFor("booked").every((step) => step.state === "done")).toBe(true);
  });

  it("after a dearer rebooking shows a Top-up alert, not a fresh Paying step", () => {
    const shares = [
      { paid_minor: 54_800, outstanding_minor: 1_890 },
      { paid_minor: 54_800, outstanding_minor: 1_890 },
    ];
    expect(owesTopUp("paying", shares)).toBe(true);
    expect(owesTopUp("paying", [{ paid_minor: 0, outstanding_minor: 54_800 }])).toBe(false);
    expect(owesTopUp("rebooking", shares)).toBe(false);
    const steps = stepsFor("paying", { topUp: true });
    expect(steps.map((step) => [step.label, step.state])).toEqual([
      ["Collecting", "done"],
      ["Voting", "done"],
      ["Top-up", "alert"],
      ["Rebooking", "upcoming"],
      ["Booked", "upcoming"],
    ]);
  });
});
