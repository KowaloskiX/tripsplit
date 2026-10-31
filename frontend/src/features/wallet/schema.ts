import { z } from "zod";

/** Per top-up, like the backend: 1 zł .. 10 000 zł. */
export const MIN_TOP_UP_MINOR = 100;
export const MAX_TOP_UP_MINOR = 1_000_000;
export const TOP_UP_PRESETS_MINOR = [10_000, 25_000, 50_000] as const;

/** What a top-up sends besides the amount: a BLIK code, or the card's last four digits. */
export type PaymentDetails =
  | { method: "blik"; blik_code: string }
  | { method: "card"; card_last4: string };

/** "250", "250,50" or "250.5" zł -> minor units; null when it is not an amount. */
export function parseAmountMinor(text: string): number | null {
  const normalized = text.trim().replace(/\s/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return null;
  return Math.round(Number(normalized) * 100);
}

export function amountError(amountMinor: number | null): string | undefined {
  if (amountMinor === null) return "Enter an amount in zł.";
  if (amountMinor < MIN_TOP_UP_MINOR) return "At least 1 zł.";
  if (amountMinor > MAX_TOP_UP_MINOR) return "At most 10 000 zł per top-up.";
  return undefined;
}

export const blikCodeSchema = z
  .string()
  .regex(/^\d{6}$/, { message: "Six digits from your bank app." });

/** The Luhn checksum every real card number (and every test card) satisfies. */
export function luhnValid(digits: string): boolean {
  let sum = 0;
  for (let index = 0; index < digits.length; index += 1) {
    let digit = Number(digits[digits.length - 1 - index]);
    if (index % 2 === 1) {
      digit *= 2;
      if (digit > 9) digit -= 9;
    }
    sum += digit;
  }
  return digits.length >= 12 && sum % 10 === 0;
}

function expiryInFuture(value: string, now: Date): boolean {
  const match = /^(\d{2})\s*\/\s*(\d{2})$/.exec(value);
  if (!match) return false;
  const month = Number(match[1]);
  const year = 2000 + Number(match[2]);
  if (month < 1 || month > 12) return false;
  return year > now.getFullYear() || (year === now.getFullYear() && month >= now.getMonth() + 1);
}

/**
 * The fake card form. The full number never leaves the browser: only the last four digits are
 * sent, after the checksum says it is a plausible (test) card such as 4242 4242 4242 4242.
 */
export function cardSchema(now: Date = new Date()) {
  return z.object({
    number: z
      .string()
      .transform((value) => value.replace(/[\s-]/g, ""))
      .refine((digits) => /^\d{12,19}$/.test(digits) && luhnValid(digits), {
        message: "Not a valid card number — try 4242 4242 4242 4242.",
      }),
    expiry: z.string().refine((value) => expiryInFuture(value.trim(), now), {
      message: "MM/YY, in the future.",
    }),
    cvc: z.string().regex(/^\d{3,4}$/, { message: "3 or 4 digits." }),
  });
}
