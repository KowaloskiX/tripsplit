import { z } from "zod";

import type { CreateTripRequest } from "@/lib/api";

/** Must match `MAX_GROUP_SIZE` on the backend. */
export const MAX_GROUP_SIZE = 20;

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
