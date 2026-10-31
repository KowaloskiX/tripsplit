import { createFileRoute, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { z } from "zod";

import { Panel } from "@/components/ui/panel";
import { LoginForm, useSession } from "@/features/auth";
import { safeRedirectPath } from "@/lib/redirect";

export const Route = createFileRoute("/login")({
  // Deliberately no SSR: if the form existed before hydration, clicking "Sign in" would do a
  // NATIVE submit and push the password into the query string and the browser history.
  ssr: false,
  // `redirect`: where to return after signing in (an invite link). Vetted before use.
  validateSearch: z.object({ redirect: z.string().optional() }),
  component: LoginPage,
});

function LoginPage(): ReactNode {
  const { user, isKnown } = useSession();
  const redirectTo = safeRedirectPath(Route.useSearch().redirect);

  return (
    <div className="mx-auto w-full max-w-sm px-6 py-16 lg:py-24">
      <p className="eyebrow">sign in</p>
      <h1 className="display mt-3 text-5xl text-ink">Welcome back</h1>

      <Panel className="mt-7 p-6">
        {user ? (
          <p className="text-sm text-muted">
            You are signed in as {user.email}.{" "}
            <Link to="/app" className="text-accent underline underline-offset-2">
              Go to the dashboard
            </Link>
            .
          </p>
        ) : !isKnown ? (
          // Neither the form nor the "you are signed in" note until the session is known —
          // otherwise a signed-in user sees the login form flash before the redirect.
          <div className="h-64" aria-hidden />
        ) : (
          <LoginForm redirectTo={redirectTo} />
        )}
      </Panel>

      <p className="mt-5 text-sm text-muted">
        No account yet?{" "}
        <Link
          to="/register"
          search={redirectTo ? { redirect: redirectTo } : {}}
          className="text-accent underline underline-offset-2"
        >
          Create an account
        </Link>
        .
      </p>
    </div>
  );
}
