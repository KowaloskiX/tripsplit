import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Panel, PanelHeader } from "@/components/ui/panel";

import { useMyTrips } from "./queries";

export function TripList(): ReactNode {
  const { data: trips, isPending } = useMyTrips();

  return (
    <Panel>
      <PanelHeader>
        <span>your trips</span>
        <span>{trips?.length ?? "…"}</span>
      </PanelHeader>
      {isPending ? (
        <p className="px-4 py-6 text-sm text-muted">Loading…</p>
      ) : !trips?.length ? (
        <p className="px-4 py-6 text-sm text-muted">
          No trips yet. Create one and send the invite link to your friends.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {trips.map(({ trip, my_role }) => (
            <li key={trip.id}>
              <Link
                to="/t/$tripId"
                params={{ tripId: trip.id }}
                className="flex items-baseline justify-between gap-4 px-4 py-3 hover:bg-surface-sunken"
              >
                <span className="min-w-0 truncate text-sm text-ink">{trip.title}</span>
                <span className="shrink-0 font-mono text-xs text-muted">
                  {trip.status} · {my_role}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
