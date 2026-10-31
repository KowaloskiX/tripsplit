import { CalendarDays, RefreshCw } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { apiErrorMessage, type RoomResponse, type TripStatus } from "@/lib/api";

import { AttractionCard } from "./attraction-card";
import { ItineraryView } from "./itinerary-view";
import { useGenerateItinerary, useToggleAttractionVote } from "./mutations";
import { useAttractions, useItinerary } from "./queries";

/** The package is chosen: the group may plan what to do there (and keep paying meanwhile). */
const AFTER_THE_VOTE: ReadonlySet<TripStatus> = new Set([
  "paying",
  "booking",
  "booked",
  "disrupted",
  "rebooking",
  "done",
]);

export function showsAttractions(status: TripStatus): boolean {
  return AFTER_THE_VOTE.has(status);
}

/** "What do we do there?": vote on attractions, then the organizer plans the days. */
export function AttractionsPanel({ room }: { room: RoomResponse }): ReactNode {
  const { trip } = room;
  const enabled = showsAttractions(trip.status);
  const attractions = useAttractions(trip.id, enabled);
  const itinerary = useItinerary(trip.id, enabled);
  const toggle = useToggleAttractionVote(trip.id);
  const plan = useGenerateItinerary(trip.id);
  if (!enabled) return null;

  const isOrganizer = room.my_role === "organizer";
  const open = trip.status !== "done";
  const list = attractions.data;
  const days = itinerary.data?.days ?? [];
  const error = attractions.error ?? toggle.error ?? plan.error;
  const path = { trip_id: trip.id };

  return (
    <Panel>
      <PanelHeader>
        <span>What do we do there?</span>
        {list && (
          <span>
            {list.destination} · {list.attractions.length} ideas
          </span>
        )}
      </PanelHeader>
      <div className="space-y-5 p-4 sm:p-5">
        {error && <ErrorCallout>{apiErrorMessage(error)}</ErrorCallout>}
        {!list && !attractions.error && (
          <div className="grid gap-3 sm:grid-cols-2">
            {[0, 1].map((key) => (
              <div
                key={key}
                className="shimmer h-56 rounded-[var(--radius-panel)] bg-surface-sunken"
              />
            ))}
          </div>
        )}
        {list && (
          <>
            <p className="text-sm text-muted">
              Tap what you want to see. Anything {list.majority} of {list.members} want goes into
              the plan first; tickets the agent can buy join the bookings.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              {list.attractions.map((attraction, index) => (
                <div
                  key={attraction.attraction_id}
                  className="rise-in"
                  style={{ "--i": Math.min(index, 8) } as CSSProperties}
                >
                  <AttractionCard
                    attraction={attraction}
                    majority={list.majority}
                    pending={toggle.isPending}
                    onToggle={
                      open
                        ? () =>
                            toggle.mutate({
                              path: { ...path, attraction_id: attraction.attraction_id },
                            })
                        : undefined
                    }
                  />
                </div>
              ))}
            </div>
          </>
        )}

        {(days.length > 0 || isOrganizer) && (
          <section aria-labelledby="plan-heading" className="space-y-3 border-t border-line pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 id="plan-heading" className="flex items-center gap-2 text-lg text-ink">
                <CalendarDays className="size-5" aria-hidden />
                The plan
              </h3>
              {isOrganizer && open && (
                <Button
                  size="sm"
                  variant={days.length > 0 && !itinerary.data?.stale ? "outline" : "solid"}
                  onClick={() => plan.mutate({ path })}
                  disabled={plan.isPending}
                >
                  {days.length > 0 && <RefreshCw className="size-4" aria-hidden />}
                  {days.length > 0 ? "Plan again" : "Plan the days"}
                </Button>
              )}
            </div>
            {itinerary.data?.stale && days.length > 0 && (
              <p className="text-xs text-muted">The votes changed since this plan was made.</p>
            )}
            {days.length > 0 ? (
              <ItineraryView days={days} />
            ) : (
              <p className="text-sm text-muted">
                No plan yet. Vote above, then plan the days around the train times.
              </p>
            )}
          </section>
        )}
      </div>
    </Panel>
  );
}
