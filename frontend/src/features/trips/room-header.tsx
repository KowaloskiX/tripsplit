import { CalendarDays, MapPin, Users } from "lucide-react";
import type { ReactNode } from "react";

import { AvatarStack } from "@/components/ui/avatar";
import { Panel } from "@/components/ui/panel";
import type { RoomResponse } from "@/lib/api";

import { InviteLink } from "./invite-link";
import { LeaveTripButton } from "./leave-trip-button";
import { owesTopUp, StatusStepper } from "./status-stepper";

function formatDates(from: string, to: string): string {
  const format = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
  return `${format.format(new Date(from))} – ${format.format(new Date(to))}`;
}

export function RoomHeader({ room }: { room: RoomResponse }): ReactNode {
  const { trip } = room;
  return (
    <header className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4 [&>*]:min-w-0">
        <div className="min-w-0 space-y-2">
          <h1 className="display text-5xl text-ink sm:text-6xl">{trip.title}</h1>
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
            <span className="inline-flex items-center gap-1.5">
              <MapPin className="size-4" aria-hidden />
              from {trip.origin}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <CalendarDays className="size-4" aria-hidden />
              <span className="ticket-mono">{formatDates(trip.date_from, trip.date_to)}</span>
            </span>
            <span className="inline-flex items-center gap-2">
              <Users className="size-4" aria-hidden />
              {room.members.length}/{trip.group_size} people
              <AvatarStack
                people={room.members.map((member) => ({
                  id: member.user_id,
                  name: member.display_name,
                }))}
                label={`Members: ${room.members.map((member) => member.display_name).join(", ")}`}
              />
            </span>
          </p>
        </div>
        <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto">
          <LeaveTripButton room={room} />
          <InviteLink inviteCode={room.invite_code} />
        </div>
      </div>
      <Panel className="px-2 py-5 sm:px-6 sm:py-6">
        <StatusStepper status={trip.status} topUp={owesTopUp(trip.status, room.contributions)} />
      </Panel>
    </header>
  );
}
