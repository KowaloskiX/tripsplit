import { MonitorSmartphone } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { RoomResponse } from "@/lib/api";

import { StageView } from "./stage-view";
import { useDemoUiStore } from "./store";

/** "Stage view" toggle for the organizer in dev, and the six phones when it is on. */
export function DemoStage({ room }: { room: RoomResponse }): ReactNode {
  const stageView = useDemoUiStore((state) => state.stageView);
  const setStageView = useDemoUiStore((state) => state.setStageView);
  if (room.my_role !== "organizer") return null;
  return (
    <section aria-label="Demo stage" className="space-y-4">
      <div className="flex justify-end">
        <Button
          size="sm"
          variant={stageView ? "solid" : "outline"}
          aria-pressed={stageView}
          onClick={() => setStageView(!stageView)}
        >
          <MonitorSmartphone className="size-4" aria-hidden />
          Stage view
        </Button>
      </div>
      {stageView && <StageView tripId={room.trip.id} currency={room.trip.currency} />}
    </section>
  );
}
