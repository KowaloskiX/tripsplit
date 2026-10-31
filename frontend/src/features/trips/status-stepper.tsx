import type { ReactNode } from "react";

import { type Step, Stepper } from "@/components/ui/stepper";
import type { TripStatus } from "@/lib/api";

const STEPS = [
  { key: "collecting", label: "Collecting" },
  { key: "voting", label: "Voting" },
  { key: "paying", label: "Paying" },
  { key: "booking", label: "Booking" },
  { key: "booked", label: "Booked" },
] as const;

/** Where each trip status sits on the five-step happy path. */
const STEP_OF: Record<TripStatus, number> = {
  collecting: 0,
  proposing: 0,
  voting: 1,
  paying: 2,
  booking: 3,
  booked: 4,
  // A disruption sends the trip back to buying: the booking step lights up as a warning.
  disrupted: 3,
  rebooking: 3,
  done: 4,
};

/** Off-happy-path statuses rename the step they sit on, so the stepper never lies. */
const ACTIVE_LABEL: Partial<Record<TripStatus, string>> = {
  proposing: "Researching",
  disrupted: "Disrupted",
  rebooking: "Rebooking",
};

const ALERT: ReadonlySet<TripStatus> = new Set(["disrupted", "rebooking"]);

/**
 * `topUp`: the trip is paying again after a disruption made it dearer — the payment step is a
 * "Top-up" (an alert), and the booking step ahead of it is "Rebooking".
 */
export function stepsFor(status: TripStatus, { topUp = false }: { topUp?: boolean } = {}): Step[] {
  if (topUp && status === "paying") return topUpSteps();
  const current = STEP_OF[status];
  return STEPS.map((step, index) => {
    const done =
      index < current || (index === current && (status === "done" || status === "booked"));
    const state = done
      ? "done"
      : index === current
        ? ALERT.has(status)
          ? "alert"
          : "current"
        : "upcoming";
    return {
      key: step.key,
      label: (index === current && ACTIVE_LABEL[status]) || step.label,
      state,
    };
  });
}

function topUpSteps(): Step[] {
  return STEPS.map((step, index) => {
    if (index < 2) return { key: step.key, label: step.label, state: "done" };
    if (index === 2) return { key: step.key, label: "Top-up", state: "alert" };
    return { key: step.key, label: index === 3 ? "Rebooking" : step.label, state: "upcoming" };
  });
}

/**
 * A trip back in `paying` with money already in owes a top-up, not a first payment: only a
 * re-split after a disruption (or a member leaving) asks people who paid for more.
 */
export function owesTopUp(
  status: TripStatus,
  contributions: readonly { paid_minor: number; outstanding_minor: number }[],
): boolean {
  return (
    status === "paying" &&
    contributions.some((share) => share.paid_minor > 0 && share.outstanding_minor > 0)
  );
}

export function StatusStepper({
  status,
  topUp = false,
}: {
  status: TripStatus;
  topUp?: boolean;
}): ReactNode {
  return <Stepper steps={stepsFor(status, { topUp })} label="Trip progress" />;
}
