import { Rocket } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { apiErrorMessage, type TripBookingsResponse } from "@/lib/api";

import { BatchRefusals } from "./batch-refusals";
import { canStart } from "./bookings-list";
import { useStartAll } from "./mutations";

/**
 * The booking stage's primary action: one click starts every purchase of the package (the
 * agent for supplier sites, a direct summary for supplier APIs). Rule #1 is the server's.
 */
export function BookEverything({ trip }: { trip: TripBookingsResponse }): ReactNode {
  const batch = useStartAll(trip.trip_id);
  const startable = trip.bookings.filter((booking) => canStart(trip, booking));
  if (startable.length === 0 && !batch.data && !batch.error) return null;
  return (
    <div className="space-y-2">
      {startable.length > 0 && (
        <Button
          variant="sun"
          size="lg"
          className="w-full"
          disabled={batch.isPending}
          onClick={() => batch.startAll()}
        >
          <Rocket className="size-4" aria-hidden />
          {batch.isPending
            ? "Starting every purchase…"
            : `Book everything (${startable.length} purchase${startable.length === 1 ? "" : "s"})`}
        </Button>
      )}
      {batch.error && <ErrorCallout>{apiErrorMessage(batch.error)}</ErrorCallout>}
      {batch.data && <BatchRefusals items={batch.data.items} />}
    </div>
  );
}
