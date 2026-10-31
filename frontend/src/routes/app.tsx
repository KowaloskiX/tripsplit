import { createFileRoute, Link, redirect } from "@tanstack/react-router";
import { ChevronDown, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { StatusScreen } from "@/components/ui/status-screen";
import { sessionQueryOptions, useSession } from "@/features/auth";
import { CreateTripForm, TripList } from "@/features/trips";

export const Route = createFileRoute("/app")({
  // No SSR: the session lives in a browser cookie, so the guard has to run on the client.
  // Otherwise the server would render the dashboard without knowing who is asking.
  ssr: false,
  beforeLoad: async ({ context }) => {
    const session = await context.queryClient.ensureQueryData(sessionQueryOptions());
    if (!session.user) throw redirect({ to: "/login" });
  },
  component: AppPage,
  // Its own boundary, so a failure inside the dashboard does not take down the header and the
  // navigation with it — the user can still sign out or go back to the landing page.
  errorComponent: DashboardError,
});

function DashboardError({ error, reset }: { error: Error; reset: () => void }): ReactNode {
  return (
    <StatusScreen
      code="dashboard"
      title="Could not load the dashboard"
      description={error.message}
      action={
        <Button variant="ghost" size="sm" onClick={reset}>
          Try again
        </Button>
      }
    />
  );
}

function AppPage(): ReactNode {
  const { user } = useSession();
  if (!user) return null;

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 lg:py-14">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <h1 className="display text-5xl text-ink sm:text-6xl">Where to next?</h1>
        <Button asChild variant="sun" size="lg">
          <Link to="/plan">
            <Sparkles className="size-5" aria-hidden />
            Plan a trip
          </Link>
        </Button>
      </div>

      <div className="mt-10 grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <TripList />
        <Panel>
          {/* The long form is the fallback to the one-sentence plan, so it starts folded. */}
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 text-ink">
              Set every detail yourself
              <ChevronDown
                className="size-4 text-muted transition group-open:rotate-180"
                aria-hidden
              />
            </summary>
            <div className="border-t border-line p-5">
              <CreateTripForm defaultDisplayName={user.email.split("@")[0] ?? ""} />
            </div>
          </details>
        </Panel>
      </div>
    </div>
  );
}
