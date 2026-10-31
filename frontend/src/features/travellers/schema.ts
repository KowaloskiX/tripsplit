import { z } from "zod";

import type { TravellerDetailsRequest } from "@/lib/api";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const optionalDate = z
  .string()
  .refine((value) => value === "" || ISO_DATE.test(value), { message: "Pick a date." });

/**
 * Strings exactly as the inputs hold them. An empty field means "leave it as it is": the
 * document number is write-only, so the form never shows it and only sends a new one.
 */
export const travellerDetailsSchema = z.object({
  fullName: z
    .string()
    .trim()
    .max(120)
    .refine((value) => value === "" || value.split(/\s+/).length >= 2, {
      message: "First and last name, as on the document.",
    }),
  dateOfBirth: optionalDate,
  nationality: z
    .string()
    .trim()
    .refine((value) => value === "" || /^[A-Za-z]{2}$/.test(value), {
      message: "Two letters, e.g. PL.",
    }),
  documentNumber: z
    .string()
    .trim()
    .refine((value) => value === "" || /^[A-Za-z0-9 ]{5,24}$/.test(value), {
      message: "5-20 letters and digits.",
    }),
  documentExpiry: optionalDate,
  // As on the document; airlines require it. Empty = leave it as it is.
  gender: z.enum(["", "female", "male"]),
});

export type TravellerDetailsValues = z.infer<typeof travellerDetailsSchema>;

export function toTravellerDetailsBody(values: TravellerDetailsValues): TravellerDetailsRequest {
  const optional = (value: string): string | null => (value.trim() === "" ? null : value.trim());
  return {
    full_name: optional(values.fullName),
    date_of_birth: optional(values.dateOfBirth),
    nationality: optional(values.nationality)?.toUpperCase() ?? null,
    document_number: optional(values.documentNumber),
    document_expiry: optional(values.documentExpiry),
    gender: values.gender === "" ? null : values.gender,
  };
}
