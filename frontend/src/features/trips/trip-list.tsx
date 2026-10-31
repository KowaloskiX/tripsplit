import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Panel, PanelHeader } from "@/components/ui/panel";
import type { TripStatus } from "@/lib/api";

import { useMyTrips } from "./queries";

const STATUS_TONE: Record<TripStatus, BadgeTone> = {
  collecting: "neutral",
  proposing: "sky",
  voting: "sun",
  paying: "warn",
  booking: "sky",
  booked: "success",
  disrupted: "danger",
  rebooking: "warn",
  done: "neutral",
  expired: "danger",
};

export function TripList(): ReactNode {
  const { data: trips, isPending } = useMyTrips();

  return (
    <Panel>
      <PanelHeader>
        <span>Trips you are in</span>
        <span>{trips?.length ?? "…"}</span>
      </PanelHeader>
      {isPending ? (
        <p className="px-5 py-6 text-sm text-muted">Loading…</p>
      ) : !trips?.length ? (
        <p className="px-5 py-8 text-sm text-muted">
          No trips yet. Create one and send the invite link to your friends.
        </p>
      ) : (
        <ul className="divide-y divide-line p-2">
          {trips.map(({ trip, my_role }) => (
            <li key={trip.id}>
              <Link
                to="/t/$tripId"
                params={{ tripId: trip.id }}
                className="flex items-center gap-3 rounded-xl px-4 py-3.5 transition duration-150 hover:bg-surface-sunken"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-base font-medium text-ink">
                    {trip.title}
                  </span>
                  <span className="block text-xs text-muted">
                    {trip.origin} · {my_role}
                  </span>
                </span>
                <Badge tone={STATUS_TONE[trip.status]} className="capitalize">
                  {trip.status}
                </Badge>
                <ChevronRight className="size-4 shrink-0 text-muted" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
