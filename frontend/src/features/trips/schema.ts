import { z } from "zod";

import type { CreateTripRequest } from "@/lib/api";

/** Must match `MAX_GROUP_SIZE` on the backend. */
export const MAX_GROUP_SIZE = 20;
/** Must match `MAX_TRANSFERS_LIMIT` on the backend. */
export const MAX_TRANSFERS = 3;

/** Cities the enabled suppliers know well — offered as suggestions, any city is accepted. */
export const SUGGESTED_DESTINATIONS = [
  "Praha",
  "Barcelona",
  "Berlin",
  "Wien",
  "Budapest",
  "Kraków",
  "Lisbon",
  "Rome",
] as const;

export const TRANSPORT_MODES = ["any", "rail", "flight", "bus"] as const;
export type TransportChoice = (typeof TRANSPORT_MODES)[number];

export const TRANSPORT_LABELS: Record<TransportChoice, string> = {
  any: "Any",
  rail: "Train",
  flight: "Flight",
  bus: "Bus",
};

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const WHOLE_NUMBER = /^\d+$/;
const AMOUNT = /^\d+([.,]\d{1,2})?$/;

/**
 * Every field is a string, exactly as the inputs hold it; `toCreateTripBody` turns the valid
 * values into the API shape. One schema, no coercion surprises inside the form.
 */
export const createTripSchema = z
  .object({
    title: z.string().trim().min(1, "Give the trip a name.").max(120),
    origin: z.string().trim().min(1, "Where are you leaving from?").max(120),
    destination: z.string().trim().min(1, "Where are you going?").max(120),
    transportMode: z.enum(TRANSPORT_MODES),
    earliestDeparture: z
      .string()
      .refine((value) => value === "" || (WHOLE_NUMBER.test(value) && Number(value) <= 23), {
        message: "Pick an hour between 0 and 23, or leave it empty.",
      }),
    maxTransfers: z
      .string()
      .refine(
        (value) => value === "" || (WHOLE_NUMBER.test(value) && Number(value) <= MAX_TRANSFERS),
        {
          message: `At most ${MAX_TRANSFERS} changes.`,
        },
      ),
    brief: z.string().trim().max(4000, "Keep the brief under 4000 characters."),
    dateFrom: z.string().regex(ISO_DATE, "Pick the start date."),
    dateTo: z.string().regex(ISO_DATE, "Pick the end date."),
    groupSize: z
      .string()
      .regex(WHOLE_NUMBER, "Enter a whole number of people.")
      .refine((value) => Number(value) >= 1 && Number(value) <= MAX_GROUP_SIZE, {
        message: `A group has between 1 and ${MAX_GROUP_SIZE} people.`,
      }),
    budgetPerPerson: z
      .string()
      .trim()
      .refine((value) => value === "" || AMOUNT.test(value), {
        message: "Enter an amount like 450 or 450.50, or leave it empty.",
      }),
    displayName: z.string().trim().min(1, "How should the group call you?").max(60),
  })
  .refine((values) => values.dateTo >= values.dateFrom, {
    message: "The trip cannot end before it starts.",
    path: ["dateTo"],
  });

export type CreateTripValues = z.infer<typeof createTripSchema>;

export function toCreateTripBody(values: CreateTripValues): CreateTripRequest {
  const budget = values.budgetPerPerson.replace(",", ".");
  return {
    title: values.title,
    origin: values.origin,
    destination: values.destination,
    transport_mode: values.transportMode === "any" ? null : values.transportMode,
    earliest_departure_hour:
      values.earliestDeparture === "" ? null : Number(values.earliestDeparture),
    max_transfers: values.maxTransfers === "" ? null : Number(values.maxTransfers),
    brief: values.brief,
    date_from: values.dateFrom,
    date_to: values.dateTo,
    group_size: Number(values.groupSize),
    budget_per_person_minor: budget === "" ? null : Math.round(Number(budget) * 100),
    display_name: values.displayName,
  };
}

export const joinTripSchema = z.object({
  displayName: z.string().trim().min(1, "How should the group call you?").max(60),
});

export type JoinTripValues = z.infer<typeof joinTripSchema>;
