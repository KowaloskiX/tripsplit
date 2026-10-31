import { type FormEvent, type ReactNode, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api";

import { useCompleteManually } from "./mutations";

type ManualCompletionFormProps = {
  tripId: string;
  bookingId: string;
};

/**
 * After a handoff (CAPTCHA, login wall) or a failure, the organizer finishes the purchase on
 * the supplier site and records the booking number here.
 */
export function ManualCompletionForm({ tripId, bookingId }: ManualCompletionFormProps): ReactNode {
  const id = useId();
  const [reference, setReference] = useState("");
  const completion = useCompleteManually(tripId);
  const trimmed = reference.trim();

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (trimmed) completion.complete(bookingId, trimmed);
  }

  return (
    <form onSubmit={submit} className="space-y-2" aria-label="Mark as booked manually">
      {completion.error && <ErrorCallout>{apiErrorMessage(completion.error)}</ErrorCallout>}
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1">
          <Field
            htmlFor={id}
            label="Booked it yourself?"
            hint="Enter the supplier's booking number."
          >
            <Input
              id={id}
              value={reference}
              maxLength={120}
              placeholder="e.g. PKP-123456"
              onChange={(event) => setReference(event.target.value)}
            />
          </Field>
        </div>
        <Button
          type="submit"
          size="sm"
          disabled={!trimmed || completion.isPending}
          className="mb-6"
        >
          Mark as booked manually
        </Button>
      </div>
    </form>
  );
}
