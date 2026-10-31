import type { ReactNode } from "react";

import type { RoomResponse } from "@/lib/api";

import { StageView } from "./stage-view";
import { useDemoUiStore } from "./store";

/** The six phones above the room, when "Stage view" is on in the demo controls. */
export function DemoStage({ room }: { room: RoomResponse }): ReactNode {
  const stageView = useDemoUiStore((state) => state.stageView);
  if (room.my_role !== "organizer" || !stageView) return null;
  return (
    <section aria-label="Demo stage">
      <StageView tripId={room.trip.id} currency={room.trip.currency} />
    </section>
  );
}
