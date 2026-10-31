import { type ReactNode, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import { useTopUp } from "./mutations";
import { PaymentMethodForm } from "./payment-method-form";
import { useTopUpStatus } from "./queries";
import { amountError, type PaymentDetails, parseAmountMinor, TOP_UP_PRESETS_MINOR } from "./schema";
import { useRefreshWhenSettled } from "./settle";
import { Sheet } from "./sheet";
import { TopUpProgress } from "./top-up-progress";

type AmountPickerProps = {
  amountMinor: number | null;
  custom: string;
  onPreset: (amountMinor: number) => void;
  onCustom: (text: string) => void;
};

export function AmountPicker({
  amountMinor,
  custom,
  onPreset,
  onCustom,
}: AmountPickerProps): ReactNode {
  const id = useId();
  return (
    <div className="space-y-3">
      <fieldset className="grid grid-cols-3 gap-2">
        <legend className="sr-only">Amount</legend>
        {TOP_UP_PRESETS_MINOR.map((preset) => (
          <button
            key={preset}
            type="button"
            aria-pressed={custom === "" && amountMinor === preset}
            onClick={() => onPreset(preset)}
            className={cn(
              "h-12 rounded-[var(--radius-control)] border text-base font-medium tabular-nums transition duration-150",
              custom === "" && amountMinor === preset
                ? "border-ink bg-ink text-bg"
                : "border-line text-ink hover:border-ink/40",
            )}
          >
            {formatMoney(preset)}
          </button>
        ))}
      </fieldset>
      <Field
        htmlFor={`${id}-custom`}
        label="Or another amount (zł)"
        error={custom === "" ? undefined : amountError(amountMinor)}
      >
        <Input
          id={`${id}-custom`}
          inputMode="decimal"
          placeholder="e.g. 120"
          value={custom}
          onChange={(event) => onCustom(event.target.value)}
        />
      </Field>
    </div>
  );
}

/** "Top up" on the wallet page: amount -> BLIK / card -> the bank confirms. */
export function TopUpSheet({ open, onClose }: { open: boolean; onClose: () => void }): ReactNode {
  const [preset, setPreset] = useState<number>(TOP_UP_PRESETS_MINOR[1]);
  const [custom, setCustom] = useState("");
  const [entryId, setEntryId] = useState<string | null>(null);
  const topUp = useTopUp();
  const status = useTopUpStatus(entryId);
  useRefreshWhenSettled(status.data?.status);

  const amountMinor = custom === "" ? preset : parseAmountMinor(custom);
  const invalid = amountError(amountMinor);

  function close() {
    setEntryId(null);
    topUp.reset();
    onClose();
  }

  function submit(details: PaymentDetails) {
    if (amountMinor === null || invalid) return;
    topUp.mutate(
      { body: { amount_minor: amountMinor, ...details } },
      { onSuccess: (entry) => setEntryId(entry.id) },
    );
  }

  const entry = status.data;
  return (
    <Sheet open={open} onClose={close} title="Top up your wallet">
      {entry ? (
        <div className="space-y-4">
          <TopUpProgress entry={entry} />
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
          <AmountPicker
            amountMinor={amountMinor}
            custom={custom}
            onPreset={(value) => {
              setPreset(value);
              setCustom("");
            }}
            onCustom={setCustom}
          />
          {topUp.error && <ErrorCallout>{apiErrorMessage(topUp.error)}</ErrorCallout>}
          <PaymentMethodForm
            submitLabel={
              invalid || amountMinor === null ? "Top up" : `Top up ${formatMoney(amountMinor)}`
            }
            pending={topUp.isPending}
            disabled={Boolean(invalid)}
            onSubmit={submit}
          />
        </div>
      )}
    </Sheet>
  );
}
