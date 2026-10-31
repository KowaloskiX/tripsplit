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
  // The funding deadline passed: the escrow refunded everyone, the paying step stays red.
  expired: 2,
};

/** Off-happy-path statuses rename the step they sit on, so the stepper never lies. */
const ACTIVE_LABEL: Partial<Record<TripStatus, string>> = {
  proposing: "Researching",
  disrupted: "Disrupted",
  rebooking: "Rebooking",
  expired: "Expired",
};

const ALERT: ReadonlySet<TripStatus> = new Set(["disrupted", "rebooking", "expired"]);

export function stepsFor(status: TripStatus): Step[] {
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

export function StatusStepper({ status }: { status: TripStatus }): ReactNode {
  return <Stepper steps={stepsFor(status)} label="Trip progress" />;
}
