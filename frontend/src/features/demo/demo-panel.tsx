import { MonitorSmartphone } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { apiErrorMessage, type RoomResponse } from "@/lib/api";

import { useMemberLeaves, usePayAll, useSeedMembers, useVoteAll } from "./mutations";
import { useDemoUiStore } from "./store";

const LEAVABLE = ["collecting", "proposing", "voting", "paying"];

/**
 * Dev-only shortcuts for a six-person demo from one browser. The backend refuses these routes
 * outside dev/test as well — hiding the panel is convenience, not protection.
 */
export function DemoPanel({ room }: { room: RoomResponse }): ReactNode {
  const { trip } = room;
  const path = { trip_id: trip.id };
  const seed = useSeedMembers(trip.id);
  const voteAll = useVoteAll(trip.id);
  const payAll = usePayAll(trip.id);
  const memberLeaves = useMemberLeaves(trip.id);
  const error = seed.error ?? voteAll.error ?? payAll.error ?? memberLeaves.error;
  // Seeded members join after the real ones, so the newest non-organizer is the one to drop.
  const leaver = [...room.members]
    .reverse()
    .find((member) => member.role !== "organizer" && member.user_id !== room.my_user_id);
  const missing = trip.group_size - room.members.length;
  const joinable = ["collecting", "proposing", "voting"].includes(trip.status);
  const favourite = room.my_vote_proposal_id ?? room.proposals[0]?.id;
  const stageView = useDemoUiStore((state) => state.stageView);
  const setStageView = useDemoUiStore((state) => state.setStageView);

  return (
    <details className="mx-auto w-full max-w-3xl rounded-[var(--radius-panel)] border border-dashed border-line px-4 py-2.5 text-center open:text-left">
      <summary className="cursor-pointer text-xs font-medium text-muted">
        Demo<span className="sr-only"> controls (dev only)</span>
      </summary>
      <div className="mt-3 space-y-3">
        {error && <ErrorCallout>{apiErrorMessage(error)}</ErrorCallout>}
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={seed.isPending || missing < 1 || !joinable}
            onClick={() => seed.mutate({ path, body: { count: missing } })}
          >
            {missing < 1 ? "Group is full" : `Seed ${missing} member${missing === 1 ? "" : "s"}`}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={voteAll.isPending || trip.status !== "voting" || !favourite}
            onClick={() => favourite && voteAll.mutate({ path, body: { proposal_id: favourite } })}
          >
            Everyone votes {room.my_vote_proposal_id ? "like me" : "for the first"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={payAll.isPending || trip.status !== "paying"}
            onClick={() => payAll.mutate({ path })}
          >
            Everyone else pays
          </Button>
          {room.my_role === "organizer" && (
            <Button
              size="sm"
              variant={stageView ? "solid" : "outline"}
              aria-pressed={stageView}
              onClick={() => setStageView(!stageView)}
            >
              <MonitorSmartphone className="size-4" aria-hidden />
              Stage view
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            disabled={memberLeaves.isPending || !leaver || !LEAVABLE.includes(trip.status)}
            onClick={() =>
              leaver && memberLeaves.mutate({ path, body: { user_id: leaver.user_id } })
            }
          >
            {leaver ? `${leaver.display_name} drops out` : "Nobody to drop out"}
          </Button>
        </div>
      </div>
    </details>
  );
}
