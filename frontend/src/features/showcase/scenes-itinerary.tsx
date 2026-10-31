import type { CSSProperties, ReactNode } from "react";

import { Panel, PanelHeader } from "@/components/ui/panel";
import { AttractionCard, ItineraryView } from "@/features/itinerary";

import { planDays, withVoters } from "./fixtures-itinerary";
import { cueIndex, useSceneClock } from "./timeline";

const VOTE_CUES = [600, 1300, 2000, 2700, 3400, 4100];

/** What do we do there: votes land on the cards one by one, avatars stack, counts roll. */
export function AttractionsScene(): ReactNode {
  const elapsed = useSceneClock(5000);
  const step = cueIndex(VOTE_CUES, elapsed);
  const counts = [Math.min(step, 6), Math.min(step, 4), Math.max(0, step - 3), step > 4 ? 2 : 0];
  const attractions = withVoters(counts);
  return (
    <Panel>
      <PanelHeader>
        <span>What do we do there?</span>
        <span>Prague · {attractions.length} ideas</span>
      </PanelHeader>
      <div className="grid gap-3 p-4 sm:grid-cols-2 sm:p-5">
        {attractions.map((attraction, index) => (
          <div
            key={attraction.attraction_id}
            className="rise-in"
            style={{ "--i": index } as CSSProperties}
          >
            <AttractionCard attraction={attraction} majority={3} onToggle={() => undefined} />
          </div>
        ))}
      </div>
    </Panel>
  );
}

/** The plan: days rise in around the trains; the museum's tickets go queued -> booked. */
export function ItineraryScene(): ReactNode {
  const elapsed = useSceneClock(6000);
  const stage = cueIndex([2500, 4200], elapsed);
  const tickets = stage === 0 ? "to_buy" : stage === 1 ? "buying" : "booked";
  return (
    <Panel>
      <PanelHeader>
        <span>The plan</span>
        <span>3 days · 4 attractions</span>
      </PanelHeader>
      <div className="p-4 sm:p-5">
        <ItineraryView days={planDays(tickets)} />
      </div>
    </Panel>
  );
}
