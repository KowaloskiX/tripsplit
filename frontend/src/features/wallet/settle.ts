import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type { WalletTransactionStatus } from "@/lib/api";

import { refreshAfterPayment } from "./mutations";

/** Once a polled top-up leaves `pending`, the balance (and the trip it paid for) is re-read. */
export function useRefreshWhenSettled(
  status: WalletTransactionStatus | undefined,
  tripId?: string,
) {
  const queryClient = useQueryClient();
  const previous = useRef(status);
  useEffect(() => {
    if (previous.current === "pending" && status !== undefined && status !== "pending") {
      void refreshAfterPayment(queryClient, tripId);
    }
    previous.current = status;
  }, [status, tripId, queryClient]);
}
