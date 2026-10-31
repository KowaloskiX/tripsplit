import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { apiErrorMessage, type RoomResponse } from "@/lib/api";

import { useCloseVoting, useGeneratePackages, useVote } from "./mutations";
import { ProposalCard } from "./proposal-card";

export function ProposalsPanel({ room }: { room: RoomResponse }): ReactNode {
  const { trip } = room;
  const path = { trip_id: trip.id };
  const generate = useGeneratePackages(trip.id);
  const vote = useVote(trip.id);
  const close = useCloseVoting(trip.id);
  const isOrganizer = room.my_role === "organizer";
  const status = trip.status;
  const error = generate.error ?? vote.error ?? close.error;

  const proposals =
    status === "voting" || status === "proposing"
      ? room.proposals
      : room.proposals.filter((proposal) => proposal.chosen);

  return (
    <Panel>
      <PanelHeader>
        <span>packages</span>
        {status === "voting" && (
          <span>{room.proposals.reduce((sum, p) => sum + p.votes, 0)} votes</span>
        )}
      </PanelHeader>
      <div className="space-y-4 p-4">
        {error && <ErrorCallout>{apiErrorMessage(error)}</ErrorCallout>}

        {status === "proposing" && (
          <p className="flex items-center gap-2 text-sm text-muted" role="status">
            <Loader2 className="size-4 animate-spin text-accent" aria-hidden />
            The agent is researching trains, stays and things to do…
          </p>
        )}

        {status === "collecting" &&
          (isOrganizer ? (
            <div className="space-y-2">
              <p className="text-sm text-muted">
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

        {proposals.length > 0 && (
          <div className="grid gap-3">
            {proposals.map((proposal) => (
              <ProposalCard
                key={proposal.id}
                proposal={proposal}
                currency={trip.currency}
                voting={vote.isPending}
                onVote={
                  status === "voting"
                    ? () => vote.mutate({ path, body: { proposal_id: proposal.id } })
                    : undefined
                }
              />
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
