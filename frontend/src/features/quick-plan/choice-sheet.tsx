import { Users, Wallet } from "lucide-react";
import type { ReactNode } from "react";

import { formatMoney } from "@/lib/money";

import type { PaymentChoice, QuickPackage } from "./model";

type ChoiceSheetProps = {
  pkg: QuickPackage;
  currency: string;
  people: number;
  onChoose?: ((choice: PaymentChoice) => void) | undefined;
};

/** After "Take this": does the group vote and pay their shares, or do you pay for everyone? */
export function ChoiceSheet({ pkg, currency, people, onChoose }: ChoiceSheetProps): ReactNode {
  const total = pkg.perPersonMinor * people;
  return (
    <section
      aria-label="How do you want to pay?"
      className="sheet-up rounded-[var(--radius-panel)] border border-line bg-surface p-4 shadow-pop sm:p-5"
    >
      <span aria-hidden className="mx-auto mb-4 block h-1 w-10 rounded-full bg-line" />
      <p className="eyebrow">You picked</p>
      <p className="mt-1 text-xl tracking-[-0.02em] text-ink">{pkg.title}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => onChoose?.("invite")}
          className="group flex flex-col items-start gap-3 rounded-xl bg-sun p-5 text-left text-sun-ink transition duration-150 hover:brightness-95 active:scale-[0.98]"
        >
          <Users className="size-6" strokeWidth={1.5} aria-hidden />
          <span className="text-lg leading-snug tracking-[-0.02em]">
            Invite friends to vote &amp; pay
          </span>
          <span className="ticket-mono text-xs opacity-70">
            {formatMoney(pkg.perPersonMinor, currency)} each · nobody fronts the money
          </span>
        </button>
        <button
          type="button"
          onClick={() => onChoose?.("pay_all")}
          className="flex flex-col items-start gap-3 rounded-xl border border-ink/15 p-5 text-left text-ink transition duration-150 hover:border-ink/40 active:scale-[0.98]"
        >
          <Wallet className="size-6" strokeWidth={1.5} aria-hidden />
          <span className="text-lg leading-snug tracking-[-0.02em]">
            I&apos;ll pay for everyone
          </span>
          <span className="ticket-mono text-xs text-muted">
            {formatMoney(total, currency)} · booked straight away
          </span>
        </button>
      </div>
    </section>
  );
}
