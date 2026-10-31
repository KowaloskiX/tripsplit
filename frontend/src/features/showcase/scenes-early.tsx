import type { ReactNode } from "react";

import { Panel } from "@/components/ui/panel";
import { ChatToTicket, HeroHeadline } from "@/features/brand";
import { ContributionsTable } from "@/features/contributions";
import { ProposalsPanel } from "@/features/proposals";
import { StatusStepper } from "@/features/trips";

import { CURRENCY, contributions, ME, room, withVotes } from "./fixtures";
import { cueIndex, useSceneClock } from "./timeline";

/** 1 · Landing: the headline cascade, then the chat thread printing a ticket. */
export function LandingScene(): ReactNode {
  return (
    <div className="dark flex flex-col items-center overflow-hidden rounded-[40px] bg-bg px-4 pt-4 pb-10 text-center text-ink sm:px-8">
      <HeroHeadline />
      <ChatToTicket />
    </div>
  );
}

/** 2 · Packages arrive: the agent researches, then three tickets are dealt. */
export function PackagesScene(): ReactNode {
  const elapsed = useSceneClock(6000);
  const researching = cueIndex([3600], elapsed) === 0;
  return (
    <ProposalsPanel
      room={room(researching ? "proposing" : "voting", researching ? [] : withVotes([0, 0, 0]))}
    />
  );
}

const VOTES = [
  [0, 0, 0],
  [1, 0, 0],
  [1, 1, 0],
  [1, 2, 0],
  [2, 2, 0],
  [3, 2, 1],
  [4, 2, 1],
] as const;
const VOTE_CUES = [0, 900, 1600, 2300, 3000, 3700, 4400];
const CLOSE_AT = 5600;

/** 3 · Voting: the counts roll, the leader glows, the winner is stamped, the rest step back. */
export function VotingScene(): ReactNode {
  const elapsed = useSceneClock(8000);
  const closed = elapsed >= CLOSE_AT;
  const step = Math.max(0, cueIndex(VOTE_CUES, elapsed) - 1);
  const votes = VOTES[step] ?? VOTES[0];
  return (
    <ProposalsPanel
      room={room(closed ? "paying" : "voting", withVotes(votes, closed ? "p1" : undefined))}
    />
  );
}

const PAY_CUES = [800, 1500, 2100, 2700, 3300, 4000];

/** 4 · Shares: each payment pops, the bar springs, the last one stamps "6/6 paid". */
export function SharesScene(): ReactNode {
  const elapsed = useSceneClock(7500);
  const paid = cueIndex(PAY_CUES, elapsed);
  const status = paid === PAY_CUES.length && elapsed >= 4900 ? "booking" : "paying";
  return (
    <div className="space-y-4">
      <Panel className="px-2 py-5 sm:px-6 sm:py-6">
        <StatusStepper status={status} />
      </Panel>
      <Panel className="p-4 sm:p-5">
        <ContributionsTable contributions={contributions(paid)} currency={CURRENCY} myUserId={ME} />
      </Panel>
    </div>
  );
}
