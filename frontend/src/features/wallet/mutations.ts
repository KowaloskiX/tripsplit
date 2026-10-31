import { type QueryClient, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  contributionsPayMutation,
  contributionsTopUpAndPayMutation,
  tripsFeedQueryKey,
  tripsRoomQueryKey,
  walletReadQueryKey,
  walletTopUpMutation,
} from "@/lib/api";

/** After money moved: the balance, and the room + feed of the trip it moved for. */
export async function refreshAfterPayment(queryClient: QueryClient, tripId?: string) {
  const reads = [queryClient.invalidateQueries({ queryKey: walletReadQueryKey() })];
  if (tripId !== undefined) {
    const path = { trip_id: tripId };
    reads.push(
      queryClient.invalidateQueries({ queryKey: tripsRoomQueryKey({ path }) }),
      queryClient.invalidateQueries({ queryKey: tripsFeedQueryKey({ path }) }),
    );
  }
  await Promise.all(reads);
}

export function useTopUp() {
  const queryClient = useQueryClient();
  return useMutation({
    ...walletTopUpMutation(),
    onSuccess: () => refreshAfterPayment(queryClient),
  });
}

export function usePayFromWallet(tripId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    ...contributionsPayMutation(),
    onSuccess: () => refreshAfterPayment(queryClient, tripId),
  });
}

export function useTopUpAndPay(tripId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    ...contributionsTopUpAndPayMutation(),
    onSuccess: () => refreshAfterPayment(queryClient, tripId),
  });
}
