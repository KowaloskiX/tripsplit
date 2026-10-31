import { createFileRoute, Link, redirect } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { FoldedSection } from "@/components/ui/disclosure";
import { StatusScreen } from "@/components/ui/status-screen";
import { sessionQueryOptions } from "@/features/auth";
import { LiveMissionControl, TripBookings } from "@/features/bookings";
import { ContributionsPanel } from "@/features/contributions";
import { DemoPanel, DemoStage } from "@/features/demo";
import { TripFeed } from "@/features/feed";
import { AttractionsPanel, showsAttractions } from "@/features/itinerary";
import { ProposalsPanel } from "@/features/proposals";
import { detailsNeeded, TravellerDetailsPanel } from "@/features/travellers";
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

  const { trip } = room;
  const status = trip.status;
  const showContributions = room.contributions.length > 0;
  const showBookings = BOOKING_PHASE.has(status);
  const paying = status === "paying";
  const deciding = !showBookings && status !== "expired";
  const me = room.members.find((member) => member.user_id === room.my_user_id);
  const ready = room.members.filter((member) => member.traveller_details_complete).length;

  return (
    <div className="mx-auto w-full max-w-6xl space-y-10 px-4 py-8 sm:px-6 lg:py-12">
      <RoomHeader room={room} />
      {import.meta.env.DEV && <DemoStage room={room} />}
      {/* Only while a purchase is actually running. */}
      {showBookings && <LiveMissionControl tripId={tripId} title={trip.title} />}
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-8 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="flex min-w-0 flex-col gap-6">
          {/* The stage card: the one thing that needs doing now. */}
          {(deciding || paying) && !showContributions && <ProposalsPanel room={room} />}
          {/* Kept in one JSX slot from paying on, so its "everyone paid" moment can play. */}
          {showContributions && (
            <div className={paying ? "order-1" : "order-2"}>
              <ContributionsPanel room={room} />
            </div>
          )}
          {showBookings && !paying && (
            <section aria-labelledby="bookings-heading" className="order-1 space-y-3">
              <div className="flex items-baseline justify-between gap-3">
                <h2 id="bookings-heading" className="display text-3xl text-ink">
                  Bookings
                </h2>
                <Link
                  to="/t/$tripId/bookings"
                  params={{ tripId }}
                  className="text-sm font-medium text-muted underline-offset-4 hover:text-ink hover:underline"
                >
                  Full screen
                </Link>
              </div>
              <TripBookings tripId={tripId} />
            </section>
          )}

          {/* Everything else, folded into quiet rows. */}
          <div className="order-3 flex flex-col gap-2">
            {paying && <ProposalsPanel room={room} />}
            {paying && (
              <FoldedSection title="What will be booked" className="mt-4">
                <TripBookings tripId={tripId} />
              </FoldedSection>
            )}
            {showBookings && !paying && (
              <FoldedSection title="The package">
                <ProposalsPanel room={room} />
              </FoldedSection>
            )}
            {showsAttractions(status) && (
              <FoldedSection title="Things to do there" hint="vote and plan the days">
                <AttractionsPanel room={room} />
              </FoldedSection>
            )}
            <FoldedSection
              title="Traveller details"
              hint={`${ready}/${room.members.length} ready`}
              open={me ? detailsNeeded(status, me.traveller_details_complete) : false}
            >
              <TravellerDetailsPanel room={room} embedded />
            </FoldedSection>
            {showContributions && (
              <FoldedSection title="Trip money" hint="held by the payment partner">
                <TripPotCard pot={room.pot} currency={trip.currency} fundingOpen={paying} />
              </FoldedSection>
            )}
          </div>
        </div>
        <aside aria-label="Group chat" className="lg:sticky lg:top-24">
          <TripFeed tripId={tripId} myUserId={room.my_user_id} currency={trip.currency} />
        </aside>
      </div>
      {import.meta.env.DEV && <DemoPanel room={room} />}
    </div>
  );
}
