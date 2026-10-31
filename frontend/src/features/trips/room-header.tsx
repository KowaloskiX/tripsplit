import type { ReactNode } from "react";

import type { RoomResponse } from "@/lib/api";

import { InviteLink } from "./invite-link";
import { StatusStepper } from "./status-stepper";

function formatDates(from: string, to: string): string {
  const format = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
  return `${format.format(new Date(from))} – ${format.format(new Date(to))}`;
}

export function RoomHeader({ room }: { room: RoomResponse }): ReactNode {
  const { trip } = room;
  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-accent">
            {trip.origin} · {formatDates(trip.date_from, trip.date_to)} · {room.members.length}/
            {trip.group_size} people
          </p>
          <h1 className="mt-2 truncate font-mono text-2xl tracking-tight text-ink">{trip.title}</h1>
        </div>
        <InviteLink inviteCode={room.invite_code} />
      </div>
      <StatusStepper status={trip.status} />
    </header>
  );
}
