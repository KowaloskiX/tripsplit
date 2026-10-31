import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";

import { formatMoney } from "@/lib/money";

type ApprovalCardProps = {
  frameUrl: string;
  supplier: string;
  amountMinor: number;
  currency: string;
  travellers?: number | undefined;
  pending: boolean;
  onDecision: (approved: boolean) => void;
};

/** The agent stopped at the supplier's summary; nothing is paid until the organizer approves. */
export function ApprovalCard({
  frameUrl,
  supplier,
  amountMinor,
  currency,
  travellers,
  pending,
  onDecision,
}: ApprovalCardProps): ReactNode {
  const amount = formatMoney(amountMinor, currency);
  return (
    <Panel className="shadow-none" role="region" aria-label="Approve the payment">
      <PanelHeader>
        <span className="text-warn">Approval needed</span>
        <span>{supplier}</span>
      </PanelHeader>
      <div className="space-y-4 p-4">
        <img
          src={frameUrl}
          alt={`Summary page on ${supplier}`}
          className="w-full rounded-[var(--radius-control)] border border-line"
        />
        <div>
          <p className="ticket-mono text-2xl text-ink">
            {amount} <span className="text-xs text-muted">budgeted</span>
          </p>
          {/* The budget comes from the package research; the binding price is the supplier's,
              on the screenshot. Saying so beats a silent mismatch between the two numbers. */}
          <p className="mt-1 text-sm text-muted">
            {travellers ? `For ${travellers} people. ` : ""}The agent stopped before paying. The
            supplier's own total is on the summary above. Check it, then approve the final click.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button disabled={pending} onClick={() => onDecision(true)}>
            Approve and pay
          </Button>
          <Button variant="outline" disabled={pending} onClick={() => onDecision(false)}>
            Reject
          </Button>
        </div>
      </div>
    </Panel>
  );
}
