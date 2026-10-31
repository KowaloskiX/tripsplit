/**
 * A post-sign-in destination taken from the URL, or `null` when it is not safe to follow.
 *
 * Only same-origin paths: `//evil.example` and `https://…` would turn the login page into an
 * open redirect.
 */
export function safeRedirectPath(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return null;
  return value;
}
