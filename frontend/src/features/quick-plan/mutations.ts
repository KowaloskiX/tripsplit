import { useMutation } from "@tanstack/react-query";

import { tripsQuickCreateMutation } from "@/lib/api";

/** One sentence -> a trip, or the questions still to answer. */
export function useQuickCreate() {
  return useMutation(tripsQuickCreateMutation());
}
