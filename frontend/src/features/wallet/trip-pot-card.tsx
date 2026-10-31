import { PiggyBank } from "lucide-react";
import type { ReactNode } from "react";

import { Panel, PanelHeader } from "@/components/ui/panel";
import type { PotResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";

/** The trip wallet: what the group paid in, what the agent spent, what went back, what is left. */
export function TripPotCard({ pot, currency }: { pot: PotResponse; currency: string }): ReactNode {
  const rows = [
    ["Collected", pot.collected_minor],
    ["Spent on bookings", -pot.spent_minor],
    ["Refunded", -pot.refunded_minor],
  ] as const;
  return (
    <Panel>
      <PanelHeader>
        <span className="inline-flex items-center gap-2">
          <PiggyBank className="size-4" aria-hidden /> Trip wallet
        </span>
        <span>{formatMoney(pot.held_minor, currency)} held</span>
      </PanelHeader>
      <dl className="grid grid-cols-3 gap-3 p-4 sm:p-5">
        {rows.map(([label, amount]) => (
          <div key={label} className="rounded-[var(--radius-control)] bg-surface-sunken p-3">
            <dt className="text-xs text-muted">{label}</dt>
            <dd className="mt-1 text-base font-medium text-ink tabular-nums">
              {amount < 0 ? "−" : ""}
              {formatMoney(Math.abs(amount), currency)}
            </dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}
