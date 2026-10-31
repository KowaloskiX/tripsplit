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
    <div className="mx-auto w-full max-w-3xl px-6 py-12">
      <Link
        to="/t/$tripId"
        params={{ tripId }}
        className="font-mono text-xs text-muted hover:text-ink"
      >
        ← back to the trip
      </Link>
      <h1 className="mt-4 font-mono text-2xl tracking-tight text-ink">Bookings</h1>
      <p className="mt-2 max-w-lg text-sm leading-relaxed text-muted">
        The agent buys each part of the trip on the supplier's site. Watch it live; nothing is paid
        until the organizer approves the summary.
      </p>
      <div className="mt-8">
        <TripBookings tripId={tripId} />
      </div>
    </div>
  );
}
