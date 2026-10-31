import { CreditCard, Smartphone } from "lucide-react";
import { type FormEvent, type ReactNode, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { blikCodeSchema, cardSchema, type PaymentDetails } from "./schema";

type Method = PaymentDetails["method"];

type PaymentMethodFormProps = {
  submitLabel: string;
  pending?: boolean;
  /** E.g. the amount next to the form is invalid. */
  disabled?: boolean;
  onSubmit: (details: PaymentDetails) => void;
};

/** BLIK / card tabs with their (dummy) inputs. Emits the method and what the backend needs. */
export function PaymentMethodForm({
  submitLabel,
  pending = false,
  disabled = false,
  onSubmit,
}: PaymentMethodFormProps): ReactNode {
  const id = useId();
  const [method, setMethod] = useState<Method>("blik");
  const [blik, setBlik] = useState("");
  const [card, setCard] = useState({ number: "", expiry: "", cvc: "" });
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});

  function submit(event: FormEvent) {
    event.preventDefault();
    if (method === "blik") {
      const parsed = blikCodeSchema.safeParse(blik.trim());
      if (!parsed.success) {
        setErrors({ blik: parsed.error.issues[0]?.message });
        return;
      }
      setErrors({});
      onSubmit({ method: "blik", blik_code: parsed.data });
      return;
    }
    const parsed = cardSchema().safeParse(card);
    if (!parsed.success) {
      const next: Record<string, string> = {};
      for (const issue of parsed.error.issues) next[String(issue.path[0])] ??= issue.message;
      setErrors(next);
      return;
    }
    setErrors({});
    onSubmit({ method: "card", card_last4: parsed.data.number.slice(-4) });
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <div role="tablist" aria-label="Payment method" className="grid grid-cols-2 gap-2">
        {(
          [
            ["blik", "BLIK", Smartphone],
            ["card", "Card", CreditCard],
          ] as const
        ).map(([value, label, Icon]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={method === value}
            onClick={() => setMethod(value)}
            className={cn(
              "inline-flex h-11 items-center justify-center gap-2 rounded-[var(--radius-control)] border text-sm font-medium transition duration-150",
              method === value
                ? "border-ink bg-ink text-bg"
                : "border-line text-muted hover:border-ink/40 hover:text-ink",
            )}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </button>
        ))}
      </div>

      {method === "blik" ? (
        <Field
          htmlFor={`${id}-blik`}
          label="BLIK code"
          hint="Any 6 digits. 000 000 is declined by the demo bank."
          error={errors.blik}
        >
          <Input
            id={`${id}-blik`}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="123 456"
            value={blik}
            aria-invalid={errors.blik ? true : undefined}
            onChange={(event) => setBlik(event.target.value.replace(/\D/g, ""))}
            className="text-center font-mono text-xl tracking-[0.4em]"
          />
        </Field>
      ) : (
        <div className="space-y-3">
          <Field
            htmlFor={`${id}-number`}
            label="Card number"
            hint="Test card 4242 4242 4242 4242. Cards ending 0002 are declined."
            error={errors.number}
          >
            <Input
              id={`${id}-number`}
              inputMode="numeric"
              autoComplete="cc-number"
              placeholder="4242 4242 4242 4242"
              value={card.number}
              aria-invalid={errors.number ? true : undefined}
              onChange={(event) => setCard({ ...card, number: event.target.value })}
              className="font-mono"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field htmlFor={`${id}-expiry`} label="Expiry" error={errors.expiry}>
              <Input
                id={`${id}-expiry`}
                autoComplete="cc-exp"
                placeholder="MM/YY"
                value={card.expiry}
                aria-invalid={errors.expiry ? true : undefined}
                onChange={(event) => setCard({ ...card, expiry: event.target.value })}
                className="font-mono"
              />
            </Field>
            <Field htmlFor={`${id}-cvc`} label="CVC" error={errors.cvc}>
              <Input
                id={`${id}-cvc`}
                inputMode="numeric"
                autoComplete="cc-csc"
                maxLength={4}
                placeholder="123"
                value={card.cvc}
                aria-invalid={errors.cvc ? true : undefined}
                onChange={(event) => setCard({ ...card, cvc: event.target.value })}
                className="font-mono"
              />
            </Field>
          </div>
        </div>
      )}

      <Button type="submit" size="lg" className="w-full" disabled={pending || disabled}>
        {pending ? "Sending…" : submitLabel}
      </Button>
    </form>
  );
}
