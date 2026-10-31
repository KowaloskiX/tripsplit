import { ArrowDownLeft, ArrowUpRight, RotateCcw, SlidersHorizontal } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import type { WalletTransactionKind, WalletTransactionResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

const KIND: Record<WalletTransactionKind, { label: string; icon: typeof ArrowDownLeft }> = {
  top_up: { label: "Top-up", icon: ArrowDownLeft },
  share_payment: { label: "Trip share", icon: ArrowUpRight },
  refund: { label: "Refund", icon: RotateCcw },
  adjustment: { label: "Adjustment", icon: SlidersHorizontal },
};

function signed(amountMinor: number, currency: string): string {
  const text = formatMoney(Math.abs(amountMinor), currency);
  return amountMinor < 0 ? `−${text}` : `+${text}`;
}

const DATE = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function TransactionList({
  transactions,
  currency,
}: {
  transactions: WalletTransactionResponse[];
  currency: string;
}): ReactNode {
  if (transactions.length === 0) {
    return <p className="px-6 py-8 text-center text-sm text-muted">No transactions yet.</p>;
  }
  return (
    <ul className="divide-y divide-line">
      {transactions.map((entry) => {
        const { label, icon: Icon } = KIND[entry.kind];
        const credit = entry.amount_minor >= 0;
        const failed = entry.status === "failed";
        return (
          <li key={entry.id} className="flex items-center gap-3 px-5 py-3.5 sm:px-6">
            <span
              aria-hidden
              className={cn(
                "grid size-9 shrink-0 place-items-center rounded-full",
                credit ? "bg-success-soft text-success" : "bg-surface-sunken text-ink",
              )}
            >
              <Icon className="size-4" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-ink">
                {entry.trip_title ? `${label} · ${entry.trip_title}` : label}
              </p>
              <p className="truncate text-xs text-muted">
                {entry.reference || entry.method} · {DATE.format(new Date(entry.created_at))}
              </p>
            </div>
            <div className="flex flex-col items-end gap-1">
              <span
                className={cn(
                  "text-sm font-medium tabular-nums",
                  failed ? "text-muted line-through" : credit ? "text-success" : "text-ink",
                )}
              >
                {signed(entry.amount_minor, currency)}
              </span>
              {entry.status !== "completed" && (
                <Badge tone={failed ? "danger" : "warn"} pulse={entry.status === "pending"}>
                  {failed ? "declined" : "pending"}
                </Badge>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
