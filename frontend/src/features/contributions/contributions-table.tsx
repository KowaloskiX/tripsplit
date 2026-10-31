import type { ReactNode } from "react";

import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { ConfettiBurst } from "@/components/ui/confetti-burst";
import { Disclosure } from "@/components/ui/disclosure";
import { CountUp, DigitRoll } from "@/components/ui/number-roll";
import { Progress } from "@/components/ui/progress";
import { Stamp } from "@/components/ui/stamp";
import type { ContributionResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { useArrivedAt } from "@/lib/motion";

type ContributionsTableProps = {
  contributions: ContributionResponse[];
  currency: string;
  myUserId: string;
  /** Fold the per-member table behind "Who paid what" (once everyone has paid). */
  foldTable?: boolean;
};

/** Presentational: who owes what, who has paid, and how far the group is. */
export function ContributionsTable({
  contributions,
  currency,
  myUserId,
  foldTable = false,
}: ContributionsTableProps): ReactNode {
  // A former member's settled share (0, maybe a refund) is not part of the group's progress.
  const shares = contributions.filter((c) => c.amount_minor > 0);
  const paid = shares.filter((c) => c.outstanding_minor === 0).length;
  const total = shares.length;
  const allPaid = total > 0 && paid === total;
  // The last share landing while we watch: a short, classy celebration.
  const celebrate = useArrivedAt(allPaid, true, 2600);
  const paidMinor = contributions.reduce((sum, c) => sum + c.paid_minor, 0);
  // Whole units while counting, so the figure does not flicker between widths; the exact
  // amount once it lands (otherwise "6/6 paid" reads 4 442.00 of 4 442.32).
  const format = (minor: number): string =>
    formatMoney(minor === paidMinor ? minor : Math.round(minor / 100) * 100, currency);

  return (
    <div className="space-y-3">
      <div className="relative flex items-baseline justify-between gap-3">
        <p className="ticket-mono text-lg text-ink">
          <span className="sr-only">
            {paid}/{total} paid
          </span>
          <span aria-hidden>
            <DigitRoll value={paid} />/{total} paid
          </span>
        </p>
        {celebrate && (
          <span className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
            <ConfettiBurst />
            <Stamp tone="sun" rotate={-7}>
              {total}/{total} paid
            </Stamp>
          </span>
        )}
        <p className="ticket-mono text-xs text-muted">
          <CountUp value={paidMinor} format={format} /> of{" "}
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

      {foldTable ? (
        <Disclosure summary="Who paid what">
          <MemberTable contributions={contributions} currency={currency} myUserId={myUserId} />
        </Disclosure>
      ) : (
        <MemberTable contributions={contributions} currency={currency} myUserId={myUserId} />
      )}
    </div>
  );
}

function MemberTable({
  contributions,
  currency,
  myUserId,
}: Omit<ContributionsTableProps, "foldTable">): ReactNode {
  return (
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
                  // A new key on every state change remounts the badge, so it pops.
                  key={refund ? "refund" : done ? "paid" : "pending"}
                  tone={refund ? "info" : done ? "success" : "warn"}
                  className={done || refund ? "pop tabular-nums" : "tabular-nums"}
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
  );
}
