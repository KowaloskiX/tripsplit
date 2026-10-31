import { zodResolver } from "@hookform/resolvers/zod";
import type { ReactNode } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Field } from "@/components/ui/field";
import { CONTROL_CLASS, Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api";

import { useCreateTrip } from "./mutations";
import {
  type CreateTripValues,
  createTripSchema,
  MAX_GROUP_SIZE,
  MAX_TRANSFERS,
  SUGGESTED_DESTINATIONS,
  TRANSPORT_LABELS,
  TRANSPORT_MODES,
} from "./schema";

const DEPARTURE_HOURS = Array.from({ length: 13 }, (_, index) => index + 5);
const TRANSFER_CHOICES = Array.from({ length: MAX_TRANSFERS + 1 }, (_, index) => index);

type CreateTripFormProps = {
  /** Pre-fills "Your name" — e.g. the part of the email before the @. */
  defaultDisplayName?: string;
};

export function CreateTripForm({ defaultDisplayName = "" }: CreateTripFormProps): ReactNode {
  const { createTrip, isPending, error } = useCreateTrip();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateTripValues>({
    resolver: zodResolver(createTripSchema),
    defaultValues: {
      title: "",
      origin: "Warszawa",
      destination: "",
      transportMode: "any",
      earliestDeparture: "",
      maxTransfers: "",
      brief: "",
      dateFrom: "",
      dateTo: "",
      groupSize: "6",
      budgetPerPerson: "",
      displayName: defaultDisplayName,
    },
  });

  const aria = (name: keyof CreateTripValues) => ({
    "aria-invalid": errors[name] ? true : undefined,
    "aria-describedby": `${name}-message`,
  });

  return (
    <form className="space-y-4" onSubmit={handleSubmit((values) => createTrip(values))} noValidate>
      {error && <ErrorCallout>{apiErrorMessage(error)}</ErrorCallout>}

      <Field htmlFor="title" label="Trip name" error={errors.title?.message}>
        <Input
          id="title"
          placeholder="Weekend in Prague"
          {...aria("title")}
          {...register("title")}
        />
      </Field>

      <Field
        htmlFor="brief"
        label="Brief for the agent"
        hint="Where, what vibe, what matters — the agent turns this into packages."
        error={errors.brief?.message}
      >
        <Textarea
          id="brief"
          placeholder="Weekend in Prague for 6 from Warsaw, cheap, good food"
          {...aria("brief")}
          {...register("brief")}
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field htmlFor="origin" label="From" error={errors.origin?.message}>
          <Input id="origin" {...aria("origin")} {...register("origin")} />
        </Field>
        <Field htmlFor="destination" label="To" error={errors.destination?.message}>
          <Input
            id="destination"
            list="destination-suggestions"
            placeholder="Praha"
            autoComplete="off"
            {...aria("destination")}
            {...register("destination")}
          />
          <datalist id="destination-suggestions">
            {SUGGESTED_DESTINATIONS.map((city) => (
              <option key={city} value={city} />
            ))}
          </datalist>
        </Field>
        <Field htmlFor="transportMode" label="Getting there" error={errors.transportMode?.message}>
          <select
            id="transportMode"
            className={`${CONTROL_CLASS} h-11`}
            {...aria("transportMode")}
            {...register("transportMode")}
          >
            {TRANSPORT_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {TRANSPORT_LABELS[mode]}
              </option>
            ))}
          </select>
        </Field>
        <Field
          htmlFor="earliestDeparture"
          label="Leave no earlier than"
          hint="Optional, local time."
          error={errors.earliestDeparture?.message}
        >
          <select
            id="earliestDeparture"
            className={`${CONTROL_CLASS} h-11`}
            {...aria("earliestDeparture")}
            {...register("earliestDeparture")}
          >
            <option value="">Any time</option>
            {DEPARTURE_HOURS.map((hour) => (
              <option key={hour} value={String(hour)}>
                {`${String(hour).padStart(2, "0")}:00`}
              </option>
            ))}
          </select>
        </Field>
        <Field htmlFor="maxTransfers" label="Changes" error={errors.maxTransfers?.message}>
          <select
            id="maxTransfers"
            className={`${CONTROL_CLASS} h-11`}
            {...aria("maxTransfers")}
            {...register("maxTransfers")}
          >
            <option value="">Any</option>
            {TRANSFER_CHOICES.map((count) => (
              <option key={count} value={String(count)}>
                {count === 0 ? "Direct only" : `Up to ${count}`}
              </option>
            ))}
          </select>
        </Field>
        <Field htmlFor="groupSize" label="People" error={errors.groupSize?.message}>
          <Input
            id="groupSize"
            type="number"
            min={1}
            max={MAX_GROUP_SIZE}
            inputMode="numeric"
            {...aria("groupSize")}
            {...register("groupSize")}
          />
        </Field>
        <Field htmlFor="dateFrom" label="Start" error={errors.dateFrom?.message}>
          <Input id="dateFrom" type="date" {...aria("dateFrom")} {...register("dateFrom")} />
        </Field>
        <Field htmlFor="dateTo" label="End" error={errors.dateTo?.message}>
          <Input id="dateTo" type="date" {...aria("dateTo")} {...register("dateTo")} />
        </Field>
        <Field
          htmlFor="budgetPerPerson"
          label="Budget per person (PLN)"
          hint="Optional."
          error={errors.budgetPerPerson?.message}
        >
          <Input
            id="budgetPerPerson"
            inputMode="decimal"
            placeholder="600"
            {...aria("budgetPerPerson")}
            {...register("budgetPerPerson")}
          />
        </Field>
        <Field htmlFor="displayName" label="Your name" error={errors.displayName?.message}>
          <Input
            id="displayName"
            autoComplete="given-name"
            {...aria("displayName")}
            {...register("displayName")}
          />
        </Field>
      </div>

      <Button type="submit" className="w-full" disabled={isPending}>
        {isPending ? "Creating…" : "Create trip"}
      </Button>
    </form>
  );
}
