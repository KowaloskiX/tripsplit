import type { ReactNode } from "react";

import { Progress } from "@/components/ui/progress";
import type { ContributionResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

type ContributionsTableProps = {
  contributions: ContributionResponse[];
  currency: string;
  myUserId: string;
};

/** Presentational: who owes what, who has paid, and how far the group is. */
export function ContributionsTable({
  contributions,
  currency,
  myUserId,
}: ContributionsTableProps): ReactNode {
  const paid = contributions.filter((c) => c.outstanding_minor === 0).length;
  const total = contributions.length;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="font-mono text-sm text-ink">
          {paid}/{total} paid
        </p>
        <p className="font-mono text-xs text-muted">
          {formatMoney(
            contributions.reduce((sum, c) => sum + c.paid_minor, 0),
            currency,
          )}{" "}
          of{" "}
          {formatMoney(
            contributions.reduce((sum, c) => sum + c.amount_minor, 0),
            currency,
          )}
        </p>
      </div>
      <Progress value={paid} max={total} label={`${paid} of ${total} shares paid`} />

      <table className="w-full text-sm">
        <thead>
          <tr className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
            <th className="py-2 text-left font-normal">Member</th>
            <th className="py-2 text-right font-normal">Share</th>
            <th className="py-2 text-right font-normal">Paid</th>
            <th className="py-2 text-right font-normal">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {contributions.map((contribution) => {
            const done = contribution.outstanding_minor === 0;
            return (
              <tr key={contribution.user_id}>
                <td className="py-2 text-ink">
                  {contribution.display_name}
                  {contribution.user_id === myUserId && <span className="text-muted"> (you)</span>}
                </td>
                <td className="py-2 text-right font-mono text-xs text-ink">
                  {formatMoney(contribution.amount_minor, currency)}
                </td>
                <td className="py-2 text-right font-mono text-xs text-muted">
                  {formatMoney(contribution.paid_minor, currency)}
                </td>
                <td className="py-2 text-right">
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em]",
                      done ? "bg-live/15 text-live" : "bg-surface-sunken text-muted",
                    )}
                  >
                    {done ? "paid" : "pending"}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
