import { useQuery } from "@tanstack/react-query";
import { useHydrated } from "@tanstack/react-router";

import { authSessionOptions, type CurrentUserResponse } from "@/lib/api";

/**
 * One source of session state. Route loaders use the same key (`ensureQueryData`).
 *
 * Disabled during SSR on purpose: the session lives in a browser cookie and the generated
 * client uses relative URLs, so on the server the request could only fail. Left enabled, the
 * failure resolved the query to "no data", the server rendered the signed-out header, and the
 * user watched it flip after hydration.
 */
export function sessionQueryOptions() {
  return { ...authSessionOptions(), enabled: typeof window !== "undefined" };
}

export function useSession(): {
  user: CurrentUserResponse | null;
  /** `false` until the answer arrives — signed out and "not known yet" are different states. */
  isKnown: boolean;
} {
  const query = useQuery(sessionQueryOptions());
  // Until hydration finishes the answer is withheld even if it is already cached: a client-only
  // route's guard (`ensureQueryData` in `beforeLoad`) can resolve it BEFORE the server-rendered
  // header hydrates, and rendering the signed-in variant then mismatches the server's
  // placeholder. One render later it is safe.
  const hydrated = useHydrated();
  const data = hydrated ? query.data : undefined;
  return { user: data?.user ?? null, isKnown: data !== undefined };
}
