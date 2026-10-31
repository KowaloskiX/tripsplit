/**
 * One member's phone in the demo grid — the shape `GET /api/trips/{id}/demo/phones` returns
 * (demo-director). `amount` is that member's share in minor units.
 */
export type PhoneState = {
  name: string;
  initials: string;
  last_message: string | null;
  /** Title of the package this member voted for, or null. */
  voted_for: string | null;
  paid: boolean;
  amount: number;
};

export type PhonesPhase = "voting" | "paying" | "booking";

/** What the big centre counter counts in each phase: votes first, then payments. */
export function progressOf(
  phones: readonly PhoneState[],
  phase: PhonesPhase,
): { done: number; total: number; unit: "voted" | "paid" } {
  const total = phones.length;
  if (phase === "voting") {
    return {
      done: phones.filter((phone) => phone.voted_for !== null).length,
      total,
      unit: "voted",
    };
  }
  return { done: phones.filter((phone) => phone.paid).length, total, unit: "paid" };
}

/** Everyone has paid: the hand-off moment — the group is done, the agent takes over. */
export function handedOff(phones: readonly PhoneState[], phase: PhonesPhase): boolean {
  return (
    phase === "booking" || (phase === "paying" && phones.length > 0 && phones.every((p) => p.paid))
  );
}
