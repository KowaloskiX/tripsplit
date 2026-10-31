import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { tripsCreateMutation, tripsJoinMutation, tripsListQueryKey } from "@/lib/api";

import { type CreateTripValues, type JoinTripValues, toCreateTripBody } from "./schema";

/** Errors stay in `mutation.error` (rendered by the form), so the action never rejects. */
async function runQuietly(action: () => Promise<void>): Promise<void> {
  try {
    await action();
  } catch {
    // Already in `mutation.error`.
  }
}

export function useCreateTrip() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const mutation = useMutation(tripsCreateMutation());

  return {
    ...mutation,
    createTrip: (values: CreateTripValues): Promise<void> =>
      runQuietly(async () => {
        const created = await mutation.mutateAsync({ body: toCreateTripBody(values) });
        await queryClient.invalidateQueries({ queryKey: tripsListQueryKey() });
        await navigate({ to: "/t/$tripId", params: { tripId: created.trip_id } });
      }),
  };
}

export function useJoinTrip(inviteCode: string) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const mutation = useMutation(tripsJoinMutation());

  return {
    ...mutation,
    joinTrip: (values: JoinTripValues): Promise<void> =>
      runQuietly(async () => {
        const joined = await mutation.mutateAsync({
          body: { invite_code: inviteCode, display_name: values.displayName },
        });
        await queryClient.invalidateQueries({ queryKey: tripsListQueryKey() });
        await navigate({ to: "/t/$tripId", params: { tripId: joined.trip_id } });
      }),
  };
}
