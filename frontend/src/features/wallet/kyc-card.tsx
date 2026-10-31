import { BadgeCheck, IdCard } from "lucide-react";
import { type FormEvent, type ReactNode, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage, type KycResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";

import { useVerifyIdentity } from "./mutations";
import { kycSchema } from "./schema";

/** The ID check form: name + date of birth (+ an optional document, never stored by us). */
export function KycForm({ onDone }: { onDone?: () => void }): ReactNode {
  const id = useId();
  const verify = useVerifyIdentity();
  const [name, setName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [document, setDocument] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  function submit(event: FormEvent) {
    event.preventDefault();
    const parsed = kycSchema.safeParse({
      legal_name: name,
      birth_date: birthDate,
      document_number: document,
    });
    if (!parsed.success) {
      setErrors(
        Object.fromEntries(parsed.error.issues.map((issue) => [issue.path[0], issue.message])),
      );
      return;
    }
    setErrors({});
    verify.mutate({ body: parsed.data }, { onSuccess: () => onDone?.() });
  }

  if (verify.data) {
    return (
      <p className="text-sm text-ink" role="status">
        Checking your ID with Razor Trip Pay…
        {verify.data.document_masked ? ` Document ${verify.data.document_masked}.` : ""}
      </p>
    );
  }
  return (
    <form className="space-y-3" onSubmit={submit} noValidate>
      <Field htmlFor={`${id}-name`} label="Full name" error={errors.legal_name}>
        <Input
          id={`${id}-name`}
          autoComplete="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <Field htmlFor={`${id}-dob`} label="Date of birth" error={errors.birth_date}>
        <Input
          id={`${id}-dob`}
          type="date"
          value={birthDate}
          onChange={(e) => setBirthDate(e.target.value)}
        />
      </Field>
      <Field
        htmlFor={`${id}-doc`}
        label="ID document number (optional)"
        hint="Checked by the partner and forgotten — Razor Trip never stores it."
        error={errors.document_number}
      >
        <Input
          id={`${id}-doc`}
          autoComplete="off"
          value={document}
          onChange={(e) => setDocument(e.target.value)}
        />
      </Field>
      {verify.error && <ErrorCallout>{apiErrorMessage(verify.error)}</ErrorCallout>}
      <Button type="submit" className="w-full" disabled={verify.isPending}>
        Verify my ID
      </Button>
    </form>
  );
}

/** KYC light on the wallet page: the limit left, or a badge once verified. */
export function KycCard({ kyc }: { kyc: KycResponse }): ReactNode {
  const [open, setOpen] = useState(false);
  if (kyc.status === "verified") {
    return (
      <p className="inline-flex items-center gap-2 text-sm text-muted">
        <BadgeCheck className="size-4 text-success" aria-hidden /> ID verified — no top-up limit.
      </p>
    );
  }
  if (kyc.status === "pending") {
    return <p className="text-sm text-muted">Checking your ID with Razor Trip Pay…</p>;
  }
  return (
    <div className="space-y-3 rounded-[var(--radius-control)] border border-line p-4">
      <p className="inline-flex items-center gap-2 text-sm text-ink">
        <IdCard className="size-4" aria-hidden />
        {formatMoney(kyc.remaining_minor ?? 0)} of top-ups left before a quick ID check (limit{" "}
        {formatMoney(kyc.limit_minor)}).
      </p>
      {open ? (
        <KycForm />
      ) : (
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          Verify my ID now
        </Button>
      )}
    </div>
  );
}
