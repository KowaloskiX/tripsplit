import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { apiErrorMessage } from "@/lib/api";
import { formatMoney } from "@/lib/money";

import { usePayFromWallet, useTopUpAndPay } from "./mutations";
import { usePayShareStore } from "./pay-share-store";
import { PaymentMethodForm } from "./payment-method-form";
import { useTopUpStatus, useWallet } from "./queries";
import { MIN_TOP_UP_MINOR, type PaymentDetails } from "./schema";
import { useRefreshWhenSettled } from "./settle";
import { Sheet } from "./sheet";
import { TopUpProgress } from "./top-up-progress";

/** Opens the "Pay my share" sheet of `tripId` for a share of `shareMinor`. */
export function useOpenPayShare(): (tripId: string, shareMinor: number) => void {
  return usePayShareStore((state) => state.open);
}

/** "Pay my share": from the wallet, or top up exactly what is missing and pay in one go. */
export function PayShareSheet({
  tripId,
  currency,
}: {
  tripId: string;
  currency: string;
}): ReactNode {
  const {
    shareMinor,
    topUpId: entryId,
    paid,
    setTopUp: setEntryId,
    markPaid,
    close: onClose,
  } = usePayShareStore();
  const open = usePayShareStore((state) => state.tripId === tripId);
  const wallet = useWallet(open);
  const pay = usePayFromWallet(tripId);
  const topUpAndPay = useTopUpAndPay(tripId);
  const status = useTopUpStatus(open ? entryId : null);
  useRefreshWhenSettled(status.data?.status, tripId);

  const balance = wallet.data?.balance_minor ?? 0;
  const missing = Math.max(0, shareMinor - balance);
  const topUpMinor = missing > 0 ? Math.max(missing, MIN_TOP_UP_MINOR) : 0;
  const error = pay.error ?? topUpAndPay.error;

  function close() {
    pay.reset();
    topUpAndPay.reset();
    onClose();
  }

  function topUpThenPay(details: PaymentDetails) {
    topUpAndPay.mutate(
      { path: { trip_id: tripId }, body: details },
      {
        onSuccess: (checkout) => {
          if (checkout.top_up) setEntryId(checkout.top_up.id);
          else markPaid();
        },
      },
    );
  }

  const entry = status.data;
  return (
    <Sheet open={open} onClose={close} title="Pay my share">
      {paid ? (
        <div className="space-y-4 text-center">
          <p role="status" className="py-6 text-lg text-ink">
            Paid {formatMoney(shareMinor, currency)} from your wallet.
          </p>
          <Button size="lg" className="w-full" onClick={close}>
            Done
          </Button>
        </div>
      ) : entry ? (
        <div className="space-y-4">
          <TopUpProgress entry={entry} successNote="…and your share is paid from it." />
          {entry.status !== "pending" && (
            <Button
              size="lg"
              variant={entry.status === "completed" ? "solid" : "outline"}
              className="w-full"
              onClick={entry.status === "completed" ? close : () => setEntryId(null)}
            >
              {entry.status === "completed" ? "Done" : "Try again"}
            </Button>
          )}
        </div>
      ) : (
        <div className="space-y-5">
          <dl className="grid grid-cols-2 gap-3">
            <div className="rounded-[var(--radius-control)] bg-surface-sunken p-3">
              <dt className="text-xs text-muted">Your wallet</dt>
              <dd className="mt-1 text-lg font-medium text-ink tabular-nums">
                {wallet.data ? formatMoney(balance, currency) : "…"}
              </dd>
            </div>
            <div className="rounded-[var(--radius-control)] bg-surface-sunken p-3">
              <dt className="text-xs text-muted">Share</dt>
              <dd className="mt-1 text-lg font-medium text-ink tabular-nums">
                {formatMoney(shareMinor, currency)}
              </dd>
            </div>
          </dl>
          {error && <ErrorCallout>{apiErrorMessage(error)}</ErrorCallout>}
          {wallet.data && missing === 0 ? (
            <Button
              size="lg"
              className="w-full"
              disabled={pay.isPending}
              onClick={() => pay.mutate({ path: { trip_id: tripId } }, { onSuccess: markPaid })}
            >
              {pay.isPending ? "Paying…" : `Pay ${formatMoney(shareMinor, currency)} from wallet`}
            </Button>
          ) : (
            wallet.data && (
              <>
                <p className="text-sm text-muted">
                  Your wallet is {formatMoney(missing, currency)} short. Top up the difference and
                  the share is paid as soon as your bank confirms.
                </p>
                <PaymentMethodForm
                  submitLabel={`Top up ${formatMoney(topUpMinor, currency)} & pay`}
                  pending={topUpAndPay.isPending}
                  onSubmit={topUpThenPay}
                />
              </>
            )
          )}
        </div>
      )}
    </Sheet>
  );
}
