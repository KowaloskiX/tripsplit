import { ArrowDown, Building2, CreditCard, Landmark, Wallet } from "lucide-react";
import type { ReactNode } from "react";

import { Sheet } from "./sheet";

const STEPS = [
  {
    icon: Wallet,
    title: "Your wallet",
    text: "BLIK or card tops up your e-money wallet at Razor Trip Pay, our (simulated) licensed payment partner. Above 1 000 zł in total it asks for a quick ID check.",
  },
  {
    icon: Landmark,
    title: "Trip escrow",
    text: "Paying your share moves money from your wallet into the trip's escrow wallet. Nothing leaves it until every share is paid — and if the group misses the pay-by deadline, everyone gets their share back automatically.",
  },
  {
    icon: Building2,
    title: "Suppliers",
    text: "Airlines and hotels with an API are paid by a payout straight from the escrow. For sites the agent books, the escrow issues a single-use virtual card for exactly that purchase; it closes after one payment.",
  },
] as const;

/** "How your money moves" — member wallet -> trip escrow -> supplier, for the demo. */
export function MoneyFlowSheet({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}): ReactNode {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="How your money moves"
      description="Razor Trip never holds your money — a licensed partner does. In this demo the partner is simulated."
    >
      <ol className="space-y-2">
        {STEPS.map((step, index) => (
          <li key={step.title}>
            <div className="flex gap-3 rounded-[var(--radius-control)] bg-surface-sunken p-3">
              <step.icon className="mt-0.5 size-5 shrink-0 text-ink" aria-hidden />
              <div>
                <p className="font-medium text-ink">{step.title}</p>
                <p className="mt-0.5 text-sm text-muted">{step.text}</p>
              </div>
            </div>
            {index < STEPS.length - 1 && (
              <ArrowDown className="mx-auto my-1 size-4 text-muted" aria-hidden />
            )}
          </li>
        ))}
      </ol>
      <p className="mt-4 inline-flex items-start gap-2 text-xs text-muted">
        <CreditCard className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        Refunds after a cheaper rebooking, and anything left over once everything is booked, go back
        from the escrow to your wallet.
      </p>
    </Sheet>
  );
}
