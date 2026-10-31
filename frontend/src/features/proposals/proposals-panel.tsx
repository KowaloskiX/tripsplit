import type { CSSProperties, ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { apiErrorMessage, type ProposalResponse, type RoomResponse } from "@/lib/api";
import { useArrivedAt } from "@/lib/motion";

import { useCloseVoting, useGeneratePackages, useVote } from "./mutations";
import { ProposalCard } from "./proposal-card";
import { ResearchProgress } from "./research-progress";

/** How long the losing packages linger, stepping back, after voting closes. */
const CLOSE_CHOREOGRAPHY_MS = 900;

/** The package with the most votes, if exactly one leads — a tie has no leader. */
export function leaderOf(proposals: readonly ProposalResponse[]): string | null {
  const top = Math.max(0, ...proposals.map((proposal) => proposal.votes));
  if (top === 0) return null;
  const leaders = proposals.filter((proposal) => proposal.votes === top);
  return leaders.length === 1 ? (leaders[0]?.id ?? null) : null;
}

/** Each card is dealt from a slightly different angle, like a hand of cards. */
function dealStyle(index: number): CSSProperties {
  const rotations = [-5, 3, -2];
  const offsets = [-28, 18, -10];
  return {
    "--i": index,
    "--deal-rot": `${rotations[index % 3]}deg`,
    "--deal-x": `${offsets[index % 3]}px`,
  } as CSSProperties;
}

export function ProposalsPanel({ room }: { room: RoomResponse }): ReactNode {
  const { trip } = room;
  const path = { trip_id: trip.id };
  const generate = useGeneratePackages(trip.id);
  const vote = useVote(trip.id);
  const close = useCloseVoting(trip.id);
  const isOrganizer = room.my_role === "organizer";
  const status = trip.status;
  const error = generate.error ?? vote.error ?? close.error;
  // Voting has just closed in front of us: keep the losers on screen for a beat so the
  // winner's stamp has an audience.
  const justClosed = useArrivedAt(status === "voting", false, CLOSE_CHOREOGRAPHY_MS);

  const proposals =
    status === "voting" || status === "proposing" || justClosed
      ? room.proposals
      : room.proposals.filter((proposal) => proposal.chosen);
  const leader = status === "voting" ? leaderOf(room.proposals) : null;

  return (
    <Panel>
      <PanelHeader>
        <span>{status === "voting" ? "Vote for a package" : "Packages"}</span>
        {status === "voting" && (
          <span>{room.proposals.reduce((sum, p) => sum + p.votes, 0)} votes</span>
        )}
      </PanelHeader>
      <div className="space-y-4 p-4 sm:p-5">
        {error && <ErrorCallout>{apiErrorMessage(error)}</ErrorCallout>}

        {status === "proposing" && <ResearchProgress />}

        {status === "collecting" &&
          (isOrganizer ? (
            <div className="space-y-3">
              <p className="text-[15px] text-muted">
                When the group is in, ask the agent for three ready-to-buy packages.
              </p>
              <Button onClick={() => generate.mutate({ path })} disabled={generate.isPending}>
                Generate packages
              </Button>
            </div>
          ) : (
            <p className="text-sm text-muted">
              Waiting for the organizer to ask the agent for packages.
            </p>
          ))}

        {proposals.length > 0 && status !== "proposing" && (
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
            {proposals.map((proposal, index) => (
              <div key={proposal.id} className="deal-in min-w-0" style={dealStyle(index)}>
                <ProposalCard
                  proposal={proposal}
                  currency={trip.currency}
                  voting={vote.isPending}
                  leading={proposal.id === leader}
                  receding={justClosed && !proposal.chosen}
                  onVote={
                    status === "voting"
                      ? () => vote.mutate({ path, body: { proposal_id: proposal.id } })
                      : undefined
                  }
                />
              </div>
            ))}
          </div>
        )}

        {status === "voting" && isOrganizer && (
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => close.mutate({ path })} disabled={close.isPending}>
              Close voting
            </Button>
            <Button
              variant="ghost"
              onClick={() => generate.mutate({ path })}
              disabled={generate.isPending}
            >
              Research again
            </Button>
          </div>
        )}
      </div>
    </Panel>
  );
}
