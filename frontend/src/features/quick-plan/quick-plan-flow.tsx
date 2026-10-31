import { ArrowRight } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { useCloseVoting, useVote } from "@/features/proposals";
import { inviteUrl, useRoom } from "@/features/trips";
import { PayAllForm } from "@/features/wallet";
import { apiErrorMessage, type QuickQuestionResponse, type RoomResponse } from "@/lib/api";

import { answerFor, clarifyingQuestion, type QuickAnswers, quickPackage } from "./from-api";
import type { PaymentChoice, QuickPlanStage } from "./model";
import { useQuickCreate } from "./mutations";
import { QuickPlan } from "./quick-plan";

type QuickPlanFlowProps = {
  /** The trip this brief created (from the URL), once it exists. */
  tripId?: string | undefined;
  /** The brief became a trip: put it in the URL so a reload keeps it. */
  onTrip: (tripId: string) => void;
  /** Go on in the trip room (after the pay choice, or any time). */
  onOpenRoom: (tripId: string) => void;
};

/**
 * "Plan a trip" wired to the API: the brief goes to `POST /trips/quick`; a tapped chip answers
 * its question, a typed follow-up joins the brief (the backend reads the whole conversation)
 * and the agent's reply comes from the response. Then the created trip's packages fill the carousel; "Take this" is
 * the organizer's vote, and the pay choice either invites friends or closes the vote.
 */
export function QuickPlanFlow({ tripId, onTrip, onOpenRoom }: QuickPlanFlowProps): ReactNode {
  const [prompt, setPrompt] = useState<string | null>(null);
  const [followUps, setFollowUps] = useState<string[]>([]);
  const [answers, setAnswers] = useState<QuickAnswers>({});
  const [questions, setQuestions] = useState<QuickQuestionResponse[]>([]);
  const quick = useQuickCreate();

  const send = (text: string, next: QuickAnswers): void => {
    quick.mutate(
      { body: { text, ...next } },
      {
        onSuccess: (response) => {
          if (response.trip) {
            setQuestions([]);
            onTrip(response.trip.trip_id);
          } else {
            setQuestions(response.questions);
          }
        },
      },
    );
  };

  const conversation = (more: readonly string[]): string => [prompt, ...more].join("\n");

  const submit = (text: string): void => {
    if (tripId) return;
    if (prompt) {
      const next = [...followUps, text];
      setFollowUps(next);
      send(conversation(next), answers);
      return;
    }
    setPrompt(text);
    setFollowUps([]);
    setAnswers({});
    send(text, {});
  };

  const answer = (question: QuickQuestionResponse, option: string): void => {
    const value = answerFor(question, option);
    if (!value || !prompt) return;
    const next = { ...answers, ...value };
    setAnswers(next);
    send(conversation(followUps), next);
  };

  if (tripId) return <TripPackages tripId={tripId} prompt={prompt} onOpenRoom={onOpenRoom} />;

  const question = questions[0];
  const stage: QuickPlanStage = quick.isPending ? "thinking" : prompt ? "answered" : "idle";
  return (
    <div className="space-y-4">
      <QuickPlan
        stage={stage}
        prompt={prompt}
        followUps={followUps}
        reply={quick.data?.reply ?? ""}
        packages={[]}
        question={question ? clarifyingQuestion(question) : null}
        onSubmit={submit}
        onAnswer={(_, option) => question && answer(question, option)}
      />
      {quick.error && (
        <div className="mx-auto max-w-2xl">
          <ErrorCallout>{apiErrorMessage(quick.error)}</ErrorCallout>
        </div>
      )}
    </div>
  );
}

function copy(text: string): void {
  // A refused clipboard (insecure origin, no permission) must not block going on.
  navigator.clipboard?.writeText(text).catch(() => undefined);
}

function TripPackages({
  tripId,
  prompt,
  onOpenRoom,
}: {
  tripId: string;
  prompt: string | null;
  onOpenRoom: (tripId: string) => void;
}): ReactNode {
  const { data: room } = useRoom(tripId);
  const vote = useVote(tripId);
  const close = useCloseVoting(tripId);
  const [takenId, setTakenId] = useState<string | null>(null);
  const [payingAll, setPayingAll] = useState(false);
  const path = { trip_id: tripId };
  const proposals = room?.proposals ?? [];
  const stage: QuickPlanStage =
    proposals.length === 0 ? "thinking" : takenId ? "choosing" : "answered";

  const take = (proposalId: string): void => {
    if (room?.trip.status !== "voting") {
      setTakenId(proposalId);
      return;
    }
    vote.mutate(
      { path, body: { proposal_id: proposalId } },
      { onSuccess: () => setTakenId(proposalId) },
    );
  };

  const choose = (choice: PaymentChoice): void => {
    if (!room) return;
    if (choice === "invite") {
      copy(inviteUrl(room.invite_code));
      onOpenRoom(tripId);
      return;
    }
    // Paying for everyone: the vote is decided now, then one payment covers every share.
    if (room.trip.status !== "voting") {
      setPayingAll(true);
      return;
    }
    close.mutate({ path }, { onSuccess: () => setPayingAll(true) });
  };

  const error = vote.error ?? close.error;
  const taken = proposals.find((proposal) => proposal.id === takenId);
  // After the vote closes the shares are the truth (only the members who joined are split).
  const outstanding = (room?.contributions ?? []).reduce(
    (sum, share) => sum + share.outstanding_minor,
    0,
  );
  return (
    <div className="space-y-4">
      <QuickPlan
        stage={stage}
        prompt={prompt ?? room?.trip.brief ?? null}
        packages={proposals.map(quickPackage)}
        takenId={takenId}
        people={room?.members.length ?? 1}
        currency={room?.trip.currency ?? "PLN"}
        onTake={take}
        onChoose={choose}
      />
      {payingAll && taken && room && room.contributions.length > 0 && (
        <div className="mx-auto max-w-2xl">
          <PayAllForm
            tripId={tripId}
            totalMinor={outstanding}
            currency={room.trip.currency}
            onPaid={() => onOpenRoom(tripId)}
          />
        </div>
      )}
      {error && (
        <div className="mx-auto max-w-2xl">
          <ErrorCallout>{apiErrorMessage(error)}</ErrorCallout>
        </div>
      )}
      {room && <RoomLink room={room} onOpenRoom={onOpenRoom} />}
    </div>
  );
}

function RoomLink({
  room,
  onOpenRoom,
}: {
  room: RoomResponse;
  onOpenRoom: (tripId: string) => void;
}): ReactNode {
  return (
    <div className="flex justify-center">
      <Button size="sm" variant="ghost" onClick={() => onOpenRoom(room.trip.id)}>
        Open the trip room
        <ArrowRight className="size-4" aria-hidden />
      </Button>
    </div>
  );
}
