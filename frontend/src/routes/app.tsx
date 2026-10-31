import { createFileRoute, redirect } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";
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
    <div className="mx-auto w-full max-w-6xl px-6 py-12 lg:py-16">
      <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-accent">trips</p>
      <h1 className="mt-3 font-mono text-2xl tracking-tight text-ink">
        From group chat to tickets
      </h1>
      <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted">
        Create a trip, send the invite link, and the agent proposes three packages. The group votes,
        everyone pays their own share, and only then does the agent book.
      </p>

      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_1.2fr]">
        <TripList />
        <Panel>
          <PanelHeader>
            <span>new trip</span>
          </PanelHeader>
          <div className="p-5">
            <CreateTripForm defaultDisplayName={user.email.split("@")[0] ?? ""} />
          </div>
        </Panel>
      </div>
    </div>
  );
}
