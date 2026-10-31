import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Square, Zap } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { GroupPhones, type PhoneState, type PhonesPhase } from "@/features/group-phones";
import {
  apiErrorMessage,
  type DirectorPace,
  demoDirectorProgressOptions,
  demoDirectorProgressQueryKey,
  demoDirectorStartMutation,
  demoDirectorStopMutation,
  demoPhonesOptions,
  type PhonesResponse,
  type TripStatus,
} from "@/lib/api";

const POLL_MS = 1000;
const inBrowser = typeof window !== "undefined";

export function phonesPhase(status: TripStatus): PhonesPhase {
  if (status === "paying") return "paying";
  if (["collecting", "proposing", "voting"].includes(status)) return "voting";
  return "booking";
}

export function phoneStates(response: PhonesResponse): PhoneState[] {
  return response.phones.map((phone) => ({
    name: phone.name,
    initials: phone.initials,
    last_message: phone.last_message,
    voted_for: phone.voted_for_title,
    paid: phone.paid,
    amount: phone.amount_minor ?? 0,
  }));
}

function useDirector(tripId: string) {
  const queryClient = useQueryClient();
  const path = { trip_id: tripId };
  const progress = useQuery({
    ...demoDirectorProgressOptions({ path }),
    enabled: inBrowser,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.state === "running" || query.state.status === "pending" ? POLL_MS : false,
  });
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: demoDirectorProgressQueryKey({ path }) });
  const start = useMutation({ ...demoDirectorStartMutation(), onSuccess: refresh });
  const stop = useMutation({ ...demoDirectorStopMutation(), onSuccess: refresh });
  return { progress, start, stop };
}

/**
 * The headline scene: the six phones of the group, fed by the demo director's phones endpoint,
 * with the director's controls on top. Dev/test only — the backend 404s these routes elsewhere.
 */
export function StageView({ tripId, currency }: { tripId: string; currency: string }): ReactNode {
  const path = { trip_id: tripId };
  const phones = useQuery({
    ...demoPhonesOptions({ path }),
    enabled: inBrowser,
    refetchInterval: POLL_MS,
  });
  const { progress, start, stop } = useDirector(tripId);
  const running = progress.data?.state === "running";
  const lastBeat = progress.data?.beats.at(-1);
  const error = start.error ?? stop.error ?? (phones.data ? null : phones.error);
  const play = (pace: DirectorPace) =>
    start.mutate({ path, body: { script: "full", pace, with_disruption: true } });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={running || start.isPending} onClick={() => play("stage")}>
          <Play className="size-4" aria-hidden />
          Director: full · stage
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={running || start.isPending}
          onClick={() => play("fast")}
        >
          <Zap className="size-4" aria-hidden />
          Fast
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={!running || stop.isPending}
          onClick={() => stop.mutate({ path })}
        >
          <Square className="size-4" aria-hidden />
          Stop
        </Button>
        {progress.data && (
          <p className="ticket-mono text-xs text-muted" aria-live="polite">
            {progress.data.state} · {progress.data.phase}
            {lastBeat ? ` · ${lastBeat.actor}: ${lastBeat.text}` : ""}
          </p>
        )}
      </div>
      {progress.data?.error && <ErrorCallout>{progress.data.error}</ErrorCallout>}
      {error && <ErrorCallout>{apiErrorMessage(error)}</ErrorCallout>}
      {phones.data && (
        <GroupPhones
          phones={phoneStates(phones.data)}
          phase={phonesPhase(phones.data.status)}
          currency={currency}
        />
      )}
    </div>
  );
}
