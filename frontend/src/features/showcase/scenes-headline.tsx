import { type ReactNode, useState } from "react";

import { GroupPhones } from "@/features/group-phones";
import { MissionControl } from "@/features/mission-control";
import { ProposalCard } from "@/features/proposals";
import { QuickPlan, type QuickPlanStage } from "@/features/quick-plan";
import { LinkChips, PhotoStrip, ProvenancePill } from "@/features/trust";

import { CURRENCY, withVotes } from "./fixtures";
import {
  calls,
  fakePhoto,
  graphSteps,
  phones,
  QUESTION,
  quickPackages,
  RUN_STEPS,
  STAY_IMAGES,
  staySteps,
  TICKETS,
} from "./fixtures-live";
import { cueIndex, useSceneClock } from "./timeline";

const VOTE_CUES = [600, 1000, 1500, 1900, 2500, 3000];
const PAY_CUES = [4800, 5300, 5700, 6400, 6900, 7600];

/** Headline 1 · Six phones: votes, then payments arrive; 6/6 hands off to the agent. */
export function GroupPhonesScene(): ReactNode {
  const elapsed = useSceneClock(10_000);
  const voted = cueIndex(VOTE_CUES, elapsed);
  const paid = cueIndex(PAY_CUES, elapsed);
  const phase = elapsed < 4200 ? "voting" : elapsed < 8600 ? "paying" : "booking";
  return <GroupPhones phones={phones(voted, paid)} phase={phase} currency={CURRENCY} />;
}

const CALL_CUES = [700, 1700, 2600, 3900, 5200, 6300, 7200, 9400];
const STEP_CUES = [1200, 2400, 3600, 4800, 6000, 7400, 8800];
const STAY_CUES = [2700, 4100, 7300];

/** Headline 2 · Mission control: browser + run strip, API log, stay, tickets stacking up. */
export function MissionControlScene(): ReactNode {
  const elapsed = useSceneClock(12_500);
  const done = cueIndex(STEP_CUES, elapsed);
  const stay = cueIndex(STAY_CUES, elapsed);
  const [stayTicket, trainTicket, flightTicket] = TICKETS;
  const tickets = [
    elapsed >= 5600 ? flightTicket : undefined,
    stay >= 3 ? stayTicket : undefined,
    done >= RUN_STEPS.length ? trainTicket : undefined,
  ].filter((ticket) => ticket !== undefined);
  return (
    <MissionControl
      title="Booking Prague in December"
      currency={CURRENCY}
      purchases={3}
      browser={{ host: "www.intercity.pl/en/checkout", steps: graphSteps(done) }}
      calls={calls(cueIndex(CALL_CUES, elapsed))}
      stay={{
        title: "Riverside flat, Malá Strana",
        supplier: "LiteAPI",
        amountMinor: 132_000,
        images: STAY_IMAGES,
        provenance: { kind: "sandbox", source: "LiteAPI" },
        steps: staySteps(stay),
      }}
      tickets={tickets}
    />
  );
}

/** Plan a trip · the scripted conversation, with the real component's callbacks driving it. */
export function QuickPlanScene(): ReactNode {
  const elapsed = useSceneClock(5000);
  const [taken, setTaken] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const auto: QuickPlanStage = elapsed < 1400 ? "idle" : elapsed < 3200 ? "thinking" : "answered";
  const stage: QuickPlanStage = taken ? "choosing" : auto;
  return (
    <div className="space-y-3">
      <QuickPlan
        stage={stage}
        prompt={stage === "idle" ? null : "Prague, 4–6 Dec, 6 people, 700 zł each"}
        packages={quickPackages()}
        question={QUESTION}
        takenId={taken}
        currency={CURRENCY}
        onTake={setTaken}
        onChoose={setChosen}
      />
      {chosen && (
        <p className="rise-in ticket-mono text-center text-xs text-muted">
          → hand-off: {chosen === "invite" ? "the room, voting opens" : "mission control"}
        </p>
      )}
    </div>
  );
}

const minutesAgo = (minutes: number): string =>
  new Date(Date.now() - minutes * 60_000).toISOString();

/** Trust UI · every provenance, the check-it-yourself links, photos with a broken one. */
export function TrustScene(): ReactNode {
  const cards = withVotes([3, 1, 0]);
  const first = cards[0];
  const third = cards[2];
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        <ProvenancePill
          provenance={{ kind: "live", source: "PKP Intercity", checked_at: minutesAgo(2) }}
        />
        <ProvenancePill provenance={{ kind: "test", source: "Duffel" }} />
        <ProvenancePill provenance={{ kind: "sandbox", source: "LiteAPI" }} />
        <ProvenancePill provenance={{ kind: "example" }} />
      </div>
      <LinkChips
        links={[
          { kind: "book", label: "Open on intercity.pl", url: "https://www.intercity.pl" },
          {
            kind: "verify",
            label: "Check on Google Flights",
            url: "https://www.google.com/flights",
          },
          { kind: "status", label: "Flight status", url: "https://www.flightradar24.com" },
          { kind: "map", label: "Hotel on map", url: "https://maps.google.com" },
        ]}
      />
      <PhotoStrip
        images={[
          ...STAY_IMAGES.slice(0, 2),
          { url: "https://invalid.example/broken.jpg", alt: "A photo that failed to load" },
        ]}
      />
      <div className="grid gap-4 md:grid-cols-2">
        {first && (
          <ProposalCard
            proposal={first}
            currency={CURRENCY}
            provenance={{ kind: "live", source: "PKP Intercity", checked_at: minutesAgo(4) }}
            images={[fakePhoto(205, "Riverside flat")]}
            links={[
              { kind: "book", label: "Open on intercity.pl", url: "https://www.intercity.pl" },
              { kind: "map", label: "Hotel on map", url: "https://maps.google.com" },
            ]}
          />
        )}
        {third && (
          <ProposalCard
            proposal={third}
            currency={CURRENCY}
            provenance={{ kind: "example" }}
            images={[fakePhoto(120, "Hostel Žižkov")]}
          />
        )}
      </div>
    </div>
  );
}
