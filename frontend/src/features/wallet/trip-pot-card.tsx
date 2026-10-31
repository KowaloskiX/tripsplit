import { Info, Landmark } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";
import type { PotResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";

import { MoneyFlowSheet } from "./money-flow-sheet";

/** "1 d 4 h left", "35 min left", "deadline passed". */
export function payByLeft(payBy: string, now: number): string {
  const left = new Date(payBy).getTime() - now;
  if (left <= 0) return "deadline passed";
  const minutes = Math.floor(left / 60_000);
  const days = Math.floor(minutes / 1_440);
  const hours = Math.floor((minutes % 1_440) / 60);
  if (days > 0) return `${days} d ${hours} h left`;
  if (hours > 0) return `${hours} h ${minutes % 60} min left`;
  return `${Math.max(minutes, 1)} min left`;
}

function PayByCountdown({ payBy }: { payBy: string }): ReactNode {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <p className="px-4 pb-1 text-xs text-muted sm:px-5">
      Pay by{" "}
      <time dateTime={payBy}>
        {new Date(payBy).toLocaleString(undefined, {
          weekday: "short",
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        })}
      </time>{" "}
      · <span className="font-medium text-ink">{payByLeft(payBy, now)}</span> — otherwise every paid
      share goes back automatically.
    </p>
  );
}

/** The trip escrow at the payment partner: collected, paid to suppliers, refunded, held. */
export function TripPotCard({
  pot,
  currency,
  fundingOpen = true,
}: {
  pot: PotResponse;
  currency: string;
  fundingOpen?: boolean;
}): ReactNode {
  const [explainer, setExplainer] = useState(false);
  const reserved = pot.reserved_minor ?? 0;
  const rows = [
    ["Collected", pot.collected_minor],
    ["Paid to suppliers", -pot.spent_minor],
    ["Refunded", -pot.refunded_minor],
  ] as const;
  return (
    <Panel>
      <PanelHeader>
        <span className="inline-flex items-center gap-2">
          <Landmark className="size-4" aria-hidden /> Trip escrow
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
      {reserved > 0 && (
        <p className="px-4 pb-1 text-xs text-muted sm:px-5">
          {formatMoney(reserved, currency)} reserved on a single-use virtual card.
        </p>
      )}
      {fundingOpen && pot.pay_by && <PayByCountdown payBy={pot.pay_by} />}
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-1 pb-4 sm:px-5">
        <p className="text-xs text-muted">
          Held by {pot.held_by ?? "Razor Trip Pay"} (simulated licensed partner).
        </p>
        <Button variant="ghost" size="sm" onClick={() => setExplainer(true)}>
          <Info className="size-4" aria-hidden /> How your money moves
        </Button>
      </div>
      <MoneyFlowSheet open={explainer} onClose={() => setExplainer(false)} />
    </Panel>
  );
}
