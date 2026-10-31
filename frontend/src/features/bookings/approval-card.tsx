import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";

import { formatMoney } from "./money";

type ApprovalCardProps = {
  frameUrl: string;
  supplier: string;
  amountMinor: number;
  currency: string;
  travellers?: number | undefined;
  pending: boolean;
  onDecision: (approved: boolean) => void;
};

/**
 * The human's half of the final pay click: the agent stopped at the supplier's summary, and
 * nothing is paid until the organizer looks at it and approves.
 */
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
    <Panel className="border-accent/60" role="region" aria-label="Approve the payment">
      <PanelHeader>
        <span className="text-accent">approval needed</span>
        <span>{supplier}</span>
      </PanelHeader>
      <div className="space-y-4 p-4">
        <img
          src={frameUrl}
          alt={`Summary page on ${supplier}`}
          className="w-full rounded-[var(--radius-control)] border border-line"
        />
        <div>
          <p className="font-mono text-2xl tracking-tight text-ink">{amount}</p>
          <p className="mt-1 text-sm text-muted">
            {travellers ? `For ${travellers} people. ` : ""}The agent stopped before paying. Check
            the summary, then approve the final click.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button disabled={pending} onClick={() => onDecision(true)}>
            Approve and pay {amount}
          </Button>
          <Button variant="outline" disabled={pending} onClick={() => onDecision(false)}>
            Reject
          </Button>
        </div>
      </div>
    </Panel>
  );
}
