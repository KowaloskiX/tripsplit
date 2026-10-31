import { useQuery } from "@tanstack/react-query";

import { walletReadOptions, walletTopUpStatusOptions } from "@/lib/api";

/** How often a pending top-up is re-read while "the bank" confirms it. */
export const TOP_UP_POLL_MS = 500;

/** Refunds and demo top-ups land without the user doing anything — hence a slow poll. */
export const WALLET_POLL_MS = 5_000;

export function useWallet(enabled = true) {
  return useQuery({ ...walletReadOptions(), enabled, refetchInterval: WALLET_POLL_MS });
}

/** A top-up, polled until it leaves `pending`. */
export function useTopUpStatus(transactionId: string | null) {
  return useQuery({
    ...walletTopUpStatusOptions({ path: { transaction_id: transactionId ?? "" } }),
    enabled: transactionId !== null,
    refetchInterval: (query) => (query.state.data?.status === "pending" ? TOP_UP_POLL_MS : false),
    staleTime: 0,
  });
}
