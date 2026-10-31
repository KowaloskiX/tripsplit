import type { ReactNode } from "react";

import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import type { ContributionResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";

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
  // A former member's settled share (0, maybe a refund) is not part of the group's progress.
  const shares = contributions.filter((c) => c.amount_minor > 0);
  const paid = shares.filter((c) => c.outstanding_minor === 0).length;
  const total = shares.length;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="ticket-mono text-lg text-ink">
          {paid}/{total} paid
        </p>
        <p className="ticket-mono text-xs text-muted">
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
      <Progress
        value={paid}
        max={total}
        tone={paid === total ? "success" : "accent"}
        label={`${paid} of ${total} shares paid`}
      />

      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-muted">
            <th className="py-2 text-left font-medium">Member</th>
            <th className="py-2 text-right font-medium">Share</th>
            <th className="hidden py-2 text-right font-medium sm:table-cell">Paid</th>
            <th className="py-2 text-right font-medium">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {contributions.map((contribution) => {
            const done = contribution.outstanding_minor === 0;
            const refund = contribution.refund_minor > 0;
            return (
              <tr key={contribution.user_id}>
                <td className="py-2.5 text-ink">
                  <span className="flex items-center gap-2.5">
                    <Avatar name={contribution.display_name} size="sm" />
                    <span className="min-w-0 truncate">
                      {contribution.display_name}
                      {contribution.user_id === myUserId && (
                        <span className="text-muted"> (you)</span>
                      )}
                    </span>
                  </span>
                </td>
                <td className="ticket-mono py-2.5 text-right text-sm text-ink">
                  {formatMoney(contribution.amount_minor, currency)}
                </td>
                <td className="ticket-mono hidden py-2.5 text-right text-sm text-muted sm:table-cell">
                  {formatMoney(contribution.paid_minor, currency)}
                </td>
                <td className="py-2.5 text-right">
                  <Badge
                    tone={refund ? "info" : done ? "success" : "warn"}
                    className="tabular-nums"
                  >
                    {refund
                      ? `refund ${formatMoney(contribution.refund_minor, currency)}`
                      : done
                        ? "paid"
                        : "pending"}
                  </Badge>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
