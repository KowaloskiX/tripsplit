import { createFileRoute, Link, redirect } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { StatusScreen } from "@/components/ui/status-screen";
import { sessionQueryOptions } from "@/features/auth";
import { LiveMissionControl, TripBookings } from "@/features/bookings";
import { ContributionsPanel } from "@/features/contributions";
import { DemoPanel, DemoStage } from "@/features/demo";
import { TripFeed } from "@/features/feed";
import { AttractionsPanel } from "@/features/itinerary";
import { ProposalsPanel } from "@/features/proposals";
import { TravellerDetailsPanel } from "@/features/travellers";
import { RoomHeader, useRoom } from "@/features/trips";
import { TripPotCard } from "@/features/wallet";
import type { TripStatus } from "@/lib/api";

// Once the group has decided, buying is what the room is about: bookings move to the top.
const BOOKING_PHASE: ReadonlySet<TripStatus> = new Set([
  "paying",
  "booking",
  "booked",
  "disrupted",
  "rebooking",
  "done",
]);

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
  const { data: room, isPending } = useRoom(tripId);

  if (isPending) return <div className="h-96" aria-hidden />;
  // A failed poll (429, a blip) keeps the last room on screen; only no data at all is a 404.
  if (!room) {
    return (
      <StatusScreen
        code="404"
        title="No such trip"
        description="The link is wrong, or you are not a member of this trip. Ask for an invite link."
      />
    );
  }

  const showContributions = room.contributions.length > 0;
  const showBookings = BOOKING_PHASE.has(room.trip.status);
  const paying = room.trip.status === "paying";

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 px-4 py-8 sm:px-6 lg:py-10">
      <RoomHeader room={room} />
      {import.meta.env.DEV && <DemoStage room={room} />}
      {/* While the trip is buying, mission control takes the full width above the room. */}
      {showBookings && <LiveMissionControl tripId={tripId} title={room.trip.title} />}
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        {/* On a phone the stage card comes first: it is what needs doing now. */}
        <div className="order-2 lg:sticky lg:top-24 lg:order-1">
          <TripFeed tripId={tripId} myUserId={room.my_user_id} currency={room.trip.currency} />
        </div>
        <div className="order-1 flex flex-col gap-6 lg:order-2">
          {showBookings && (
            <section aria-labelledby="bookings-heading" className="space-y-3">
              <div className="flex items-baseline justify-between gap-3">
                <h2 id="bookings-heading" className="text-2xl tracking-[-0.03em] text-ink">
                  Bookings &amp; live agent
                </h2>
                <Link
                  to="/t/$tripId/bookings"
                  params={{ tripId }}
                  className="text-sm font-medium text-accent underline-offset-4 hover:underline"
                >
                  Full screen
                </Link>
              </div>
              <TripBookings tripId={tripId} />
            </section>
          )}
          {/* While the group pays, the shares are the stage card; afterwards the bookings are.
              Moved by CSS order, not by a second JSX slot: the panel stays mounted when the
              last share lands, so its "everyone paid" moment can play. */}
          {showContributions && (
            <div className={paying ? "-order-1 flex flex-col gap-6" : "flex flex-col gap-6"}>
              <ContributionsPanel room={room} />
              <TripPotCard pot={room.pot} currency={room.trip.currency} />
            </div>
          )}
          {/* After the package vote — while the group pays, it never blocks the money. */}
          <AttractionsPanel room={room} />
          {/* Before buying, the packages/vote card is the stage action: the (long) details
              form goes below it, collapsed. */}
          {showBookings && <TravellerDetailsPanel room={room} />}
          <ProposalsPanel room={room} />
          {!showBookings && <TravellerDetailsPanel room={room} />}
          {import.meta.env.DEV && <DemoPanel room={room} />}
        </div>
      </div>
    </div>
  );
}
