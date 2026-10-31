import type { ReactNode } from "react";

import { ErrorCallout } from "@/components/ui/callout";
import { apiErrorMessage, type PayAllResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";

import { usePayAllShares } from "./mutations";
import { PaymentMethodForm } from "./payment-method-form";

type PayAllFormProps = {
  tripId: string;
  totalMinor: number;
  currency: string;
  onPaid: (result: PayAllResponse) => void;
};

/** "I'll pay for everyone": one BLIK / card payment covers every share of the trip. */
export function PayAllForm({ tripId, totalMinor, currency, onPaid }: PayAllFormProps): ReactNode {
  const payAll = usePayAllShares(tripId);
  return (
    <section
      aria-label="Pay for everyone"
      className="sheet-up space-y-3 rounded-[var(--radius-panel)] border border-line bg-surface p-4 shadow-pop sm:p-5"
    >
      <p className="eyebrow">Pay for everyone</p>
      <p className="ticket-mono text-2xl text-ink">{formatMoney(totalMinor, currency)}</p>
      <PaymentMethodForm
        submitLabel={`Pay ${formatMoney(totalMinor, currency)}`}
        pending={payAll.isPending}
        onSubmit={(details) =>
          payAll.mutate({ path: { trip_id: tripId }, body: details }, { onSuccess: onPaid })
        }
      />
      {payAll.error && <ErrorCallout>{apiErrorMessage(payAll.error)}</ErrorCallout>}
    </section>
  );
}
