import { createFileRoute, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { z } from "zod";

import { Panel } from "@/components/ui/panel";
import { RegisterForm, useSession } from "@/features/auth";
import { safeRedirectPath } from "@/lib/redirect";

export const Route = createFileRoute("/register")({
  // See the comment in login.tsx: a native submit before hydration would carry the password
  // into the URL.
  ssr: false,
  // `redirect`: where to return after signing in (an invite link). Vetted before use.
  validateSearch: z.object({ redirect: z.string().optional() }),
  component: RegisterPage,
});

function RegisterPage(): ReactNode {
  const { user, isKnown } = useSession();
  const redirectTo = safeRedirectPath(Route.useSearch().redirect);

  return (
    <div className="mx-auto w-full max-w-sm px-6 py-16 lg:py-24">
      <p className="eyebrow">new account</p>
      <h1 className="display mt-3 text-5xl text-ink">Create your account</h1>

      <Panel className="mt-7 p-6">
        {user ? (
          <p className="text-sm text-muted">
            You are already signed in as {user.email}.{" "}
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
          <RegisterForm redirectTo={redirectTo} />
        )}
      </Panel>

      <p className="mt-5 text-sm text-muted">
        Already have an account?{" "}
        <Link
          to="/login"
          search={redirectTo ? { redirect: redirectTo } : {}}
          className="text-accent underline underline-offset-2"
        >
          Sign in
        </Link>
        .
      </p>
    </div>
  );
}
