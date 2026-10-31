import { type QueryClient, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  contributionsPayAllSharesMutation,
  contributionsPayMutation,
  contributionsTopUpAndPayMutation,
  tripsFeedQueryKey,
  tripsRoomQueryKey,
  walletKycMutation,
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

/** Simulated ID verification at the payment partner; verified about a second later. */
export function useVerifyIdentity() {
  const queryClient = useQueryClient();
  return useMutation({
    ...walletKycMutation(),
    onSuccess: async () => {
      await refreshAfterPayment(queryClient);
      // The partner verifies asynchronously: read the wallet again once it has.
      window.setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: walletReadQueryKey() });
      }, 1_300);
    },
  });
}

/** The organizer pays every outstanding share (topping their wallet up by the shortfall). */
export function usePayAllShares(tripId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    ...contributionsPayAllSharesMutation(),
    onSuccess: () => refreshAfterPayment(queryClient, tripId),
  });
}
