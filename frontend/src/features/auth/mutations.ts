import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouter } from "@tanstack/react-router";

import {
  authLoginMutation,
  authLogoutMutation,
  authRegisterMutation,
  authSessionQueryKey,
  type CurrentUserResponse,
} from "@/lib/api";

import type { LoginValues, RegisterValues } from "./schema";

/**
 * The actions return a `Promise<void>` that **never rejects**.
 *
 * Error state lives in `mutation.error` and is rendered by `ErrorCallout`, so rethrowing would
 * only produce an unhandled rejection at every call site.
 */
async function runQuietly(action: () => Promise<void>): Promise<void> {
  try {
    await action();
  } catch {
    // The message is already in `mutation.error` — see the docblock above.
  }
}

/**
 * Writes the session state straight into the cache instead of invalidating and refetching.
 *
 * The login and registration responses **are** the current user, so a refetch would only add a
 * round trip during which the UI still shows the signed-out state — which reads as "the sign-in
 * failed" for a moment. `setQueryData` flips it in the same tick.
 */
function useSessionWriter(): (user: CurrentUserResponse | null) => void {
  const queryClient = useQueryClient();
  return (user) => {
    queryClient.setQueryData(authSessionQueryKey(), { user });
  };
}

/**
 * Where to go after signing in: the page that sent the user here (an invite link), else the
 * dashboard. `redirectTo` must already be vetted by `safeRedirectPath`.
 */
function useAfterSignIn(redirectTo: string | null | undefined): () => Promise<void> {
  const navigate = useNavigate();
  const router = useRouter();
  return async () => {
    if (redirectTo) router.history.push(redirectTo);
    else await navigate({ to: "/app" });
  };
}

export function useLogin(redirectTo?: string | null) {
  const writeSession = useSessionWriter();
  const afterSignIn = useAfterSignIn(redirectTo);
  const mutation = useMutation(authLoginMutation());

  return {
    ...mutation,
    login: (values: LoginValues): Promise<void> =>
      runQuietly(async () => {
        const user = await mutation.mutateAsync({ body: values });
        writeSession(user);
        await afterSignIn();
      }),
  };
}

export function useRegister(redirectTo?: string | null) {
  const writeSession = useSessionWriter();
  const afterSignIn = useAfterSignIn(redirectTo);
  const mutation = useMutation(authRegisterMutation());

  return {
    ...mutation,
    register: (values: RegisterValues): Promise<void> =>
      runQuietly(async () => {
        const user = await mutation.mutateAsync({
          body: {
            email: values.email,
            password: values.password,
            organization_name: values.organizationName,
          },
        });
        writeSession(user);
        await afterSignIn();
      }),
  };
}

export function useLogout() {
  const writeSession = useSessionWriter();
  const navigate = useNavigate();
  const mutation = useMutation(authLogoutMutation());

  return {
    ...mutation,
    logout: (): Promise<void> =>
      runQuietly(async () => {
        await mutation.mutateAsync({});
        writeSession(null);
        await navigate({ to: "/" });
      }),
  };
}
