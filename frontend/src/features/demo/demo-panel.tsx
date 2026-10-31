import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { apiErrorMessage, type RoomResponse } from "@/lib/api";

import { usePayAll, useSeedMembers, useVoteAll } from "./mutations";

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
  const error = seed.error ?? voteAll.error ?? payAll.error;
  const missing = Math.max(trip.group_size - room.members.length, 1);
  const favourite = room.my_vote_proposal_id ?? room.proposals[0]?.id;

  return (
    <details className="rounded-[var(--radius-panel)] border border-dashed border-line px-4 py-3">
      <summary className="cursor-pointer font-mono text-[11px] uppercase tracking-[0.14em] text-muted">
        demo controls (dev only)
      </summary>
      <div className="mt-3 space-y-3">
        {error && <ErrorCallout>{apiErrorMessage(error)}</ErrorCallout>}
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={seed.isPending}
            onClick={() => seed.mutate({ path, body: { count: missing } })}
          >
            Seed {missing} member{missing === 1 ? "" : "s"}
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
        </div>
      </div>
    </details>
  );
}
