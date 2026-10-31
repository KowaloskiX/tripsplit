import { createFileRoute, Link, redirect } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { sessionQueryOptions } from "@/features/auth";
import { TripBookings } from "@/features/bookings";

export const Route = createFileRoute("/t/$tripId/bookings")({
  // The session lives in a browser cookie, so the guard runs on the client (see /app).
  ssr: false,
  beforeLoad: async ({ context, location }) => {
    const session = await context.queryClient.ensureQueryData(sessionQueryOptions());
    if (!session.user) throw redirect({ to: "/login", search: { redirect: location.href } });
  },
  component: BookingsPage,
});

function BookingsPage(): ReactNode {
  const { tripId } = Route.useParams();
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
      <Link
        to="/t/$tripId"
        params={{ tripId }}
        className="text-sm font-medium text-accent underline-offset-4 hover:underline"
      >
        ← back to the trip
      </Link>
      <h1 className="display mt-4 text-5xl text-ink">Bookings</h1>
      <p className="mt-2 max-w-lg text-base leading-relaxed text-muted">
        The agent buys each part of the trip on the supplier's site. Watch it live; nothing is paid
        until the organizer approves the summary.
      </p>
      <div className="mt-8">
        <TripBookings tripId={tripId} />
      </div>
    </div>
  );
}
