import { CircleCheck, CircleX, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import type { WalletTransactionResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";

type TopUpProgressProps = {
  entry: WalletTransactionResponse;
  /** What happens after the credit, e.g. "Your share is paid." */
  successNote?: string;
};

/** The bank's answer to a top-up: waiting for confirmation, credited, or declined. */
export function TopUpProgress({ entry, successNote }: TopUpProgressProps): ReactNode {
  const amount = formatMoney(entry.amount_minor, "PLN");
  if (entry.status === "pending") {
    return (
      <div role="status" className="flex flex-col items-center gap-3 py-6 text-center">
        <LoaderCircle
          className="size-10 animate-spin text-muted motion-reduce:animate-none"
          aria-hidden
        />
        <p className="text-lg text-ink">
          {entry.method === "blik" ? "Confirm in your bank app…" : "Authorising your card…"}
        </p>
        <p className="text-sm text-muted">
          {amount} · {entry.reference}
        </p>
      </div>
    );
  }
  if (entry.status === "completed") {
    return (
      <div role="status" className="flex flex-col items-center gap-3 py-6 text-center">
        <CircleCheck className="size-10 text-success" aria-hidden />
        <p className="text-lg text-ink">{amount} added to your wallet</p>
        {successNote && <p className="text-sm text-muted">{successNote}</p>}
      </div>
    );
  }
  return (
    <div role="alert" className="flex flex-col items-center gap-3 py-6 text-center">
      <CircleX className="size-10 text-danger" aria-hidden />
      <p className="text-lg text-ink">
        {entry.failure_reason === "expired" ? "The payment timed out" : "Your bank declined it"}
      </p>
      <p className="text-sm text-muted">Nothing was charged. Try again or use another method.</p>
    </div>
  );
}
