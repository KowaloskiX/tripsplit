/** Minor units (grosze) -> "1 234,56 zł"-style text in the user's locale. */
export function formatMoney(amountMinor: number, currency = "PLN"): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: amountMinor % 100 === 0 ? 0 : 2,
  }).format(amountMinor / 100);
}
