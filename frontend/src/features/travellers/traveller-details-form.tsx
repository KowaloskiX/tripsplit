import { zodResolver } from "@hookform/resolvers/zod";
import type { ReactNode } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage, type TravellerDetailsResponse } from "@/lib/api";

import { useUpdateTravellerDetails } from "./mutations";
import { type TravellerDetailsValues, travellerDetailsSchema } from "./schema";

type TravellerDetailsFormProps = {
  tripId: string;
  current: TravellerDetailsResponse | undefined;
};

/**
 * The current user's own details for suppliers that need more than a name (an airline). The
 * document number is write-only: the field stays empty and shows the masked stored number as
 * its placeholder; leaving it empty keeps what is stored.
 */
export function TravellerDetailsForm({ tripId, current }: TravellerDetailsFormProps): ReactNode {
  const update = useUpdateTravellerDetails(tripId);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<TravellerDetailsValues>({
    resolver: zodResolver(travellerDetailsSchema),
    values: {
      fullName: current?.full_name ?? "",
      dateOfBirth: current?.date_of_birth ?? "",
      nationality: current?.nationality ?? "",
      documentNumber: "",
      documentExpiry: current?.document_expiry ?? "",
      gender: current?.gender ?? "",
    },
  });

  return (
    <form
      className="space-y-3"
      aria-label="Your traveller details"
      onSubmit={handleSubmit((values) => update.save(values))}
      noValidate
    >
      {update.error && <ErrorCallout>{apiErrorMessage(update.error)}</ErrorCallout>}
      <Field
        htmlFor="traveller-full-name"
        label="Name on the document"
        hint="Empty = your name in this trip."
        error={errors.fullName?.message}
      >
        <Input id="traveller-full-name" autoComplete="name" {...register("fullName")} />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field htmlFor="traveller-dob" label="Date of birth" error={errors.dateOfBirth?.message}>
          <Input id="traveller-dob" type="date" autoComplete="bday" {...register("dateOfBirth")} />
        </Field>
        <Field
          htmlFor="traveller-nationality"
          label="Nationality"
          hint="Country code, e.g. PL."
          error={errors.nationality?.message}
        >
          <Input id="traveller-nationality" maxLength={2} {...register("nationality")} />
        </Field>
        <Field
          htmlFor="traveller-document"
          label="Passport / ID number"
          hint={current?.document_number_masked ? "Stored — type a new one to replace it." : ""}
          error={errors.documentNumber?.message}
        >
          <Input
            id="traveller-document"
            autoComplete="off"
            placeholder={current?.document_number_masked ?? ""}
            {...register("documentNumber")}
          />
        </Field>
        <Field
          htmlFor="traveller-expiry"
          label="Document expiry"
          error={errors.documentExpiry?.message}
        >
          <Input id="traveller-expiry" type="date" {...register("documentExpiry")} />
        </Field>
        <Field
          htmlFor="traveller-gender"
          label="Gender"
          hint="As on the document — airlines ask for it."
          error={errors.gender?.message}
        >
          <select
            id="traveller-gender"
            className="h-10 w-full rounded-[var(--radius-control)] border border-line bg-surface px-3 text-sm text-ink"
            {...register("gender")}
          >
            <option value="">—</option>
            <option value="female">Female</option>
            <option value="male">Male</option>
          </select>
        </Field>
      </div>
      <Button type="submit" size="sm" disabled={update.isPending}>
        Save my details
      </Button>
      {update.isSuccess && <p className="text-xs text-live">Saved.</p>}
    </form>
  );
}
