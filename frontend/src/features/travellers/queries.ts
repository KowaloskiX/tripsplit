import { useQuery } from "@tanstack/react-query";

import { travellerDetailsReadOptions } from "@/lib/api";

/** The caller's own traveller details (the document number comes back masked). */
export function useMyTravellerDetails() {
  return useQuery(travellerDetailsReadOptions());
}
