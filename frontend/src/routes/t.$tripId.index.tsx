import { createFileRoute, redirect } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { StatusScreen } from "@/components/ui/status-screen";
import { sessionQueryOptions } from "@/features/auth";
import { ContributionsPanel } from "@/features/contributions";
import { DemoPanel } from "@/features/demo";
import { TripFeed } from "@/features/feed";
import { ProposalsPanel } from "@/features/proposals";
import { RoomHeader, useRoom } from "@/features/trips";

export const Route = createFileRoute("/t/$tripId/")({
  // The room is private to members and the session is a browser cookie — client-only.
  ssr: false,
  beforeLoad: async ({ context, location }) => {
    const session = await context.queryClient.ensureQueryData(sessionQueryOptions());
    if (!session.user) throw redirect({ to: "/login", search: { redirect: location.href } });
  },
  component: RoomPage,
  errorComponent: RoomError,
});

function RoomError({ error, reset }: { error: Error; reset: () => void }): ReactNode {
  return (
    <StatusScreen
      code="trip"
      title="Could not load the trip"
      description={error.message}
      action={
        <Button variant="ghost" size="sm" onClick={reset}>
          Try again
        </Button>
      }
    />
  );
}

function RoomPage(): ReactNode {
  const { tripId } = Route.useParams();
  const { data: room, isPending, isError } = useRoom(tripId);

  if (isPending) return <div className="h-96" aria-hidden />;
  if (isError || !room) {
    return (
      <StatusScreen
        code="404"
        title="No such trip"
        description="The link is wrong, or you are not a member of this trip. Ask for an invite link."
      />
    );
  }

  const showContributions = room.contributions.length > 0;

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 px-6 py-10">
      <RoomHeader room={room} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <TripFeed tripId={tripId} myUserId={room.my_user_id} />
        <div className="space-y-6">
          {showContributions && <ContributionsPanel room={room} />}
          <ProposalsPanel room={room} />
          {/* A plain anchor: the bookings route belongs to the other work stream. */}
          <a
            href={`/t/${tripId}/bookings`}
            className="inline-block font-mono text-xs uppercase tracking-[0.14em] text-accent underline underline-offset-4"
          >
            Bookings &amp; live agent
          </a>
          {import.meta.env.DEV && <DemoPanel room={room} />}
        </div>
      </div>
    </div>
  );
}
