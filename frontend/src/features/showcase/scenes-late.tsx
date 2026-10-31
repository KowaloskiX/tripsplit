import { ArrowRight } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";
import {
  AgentRunGraph,
  DEMO_RAIL_GRAPH,
  DEMO_RAIL_STEPS,
  DEMO_RAIL_TOTAL_MS,
  stepsAt,
} from "@/features/agent-graph";
import { BookingsList, DisruptionAlert } from "@/features/bookings";
import { FeedList } from "@/features/feed";
import { StatusStepper } from "@/features/trips";
import { withViewTransition } from "@/lib/motion";

import { booking, bookings, CURRENCY, contributions, FEED, ME } from "./fixtures";
import { cueIndex, useSceneClock } from "./timeline";

const GRAPH_SPEED = 4;
const GRAPH_MS = DEMO_RAIL_TOTAL_MS / GRAPH_SPEED;

/** 5 · Booking: the agent works (sweep, halo, the graph lighting up), then tickets print. */
export function BookingScene(): ReactNode {
  const elapsed = useSceneClock(GRAPH_MS + 4000);
  const steps = useMemo(
    () => stepsAt(DEMO_RAIL_STEPS, Math.max(0, elapsed - 600) * GRAPH_SPEED),
    [elapsed],
  );
  const trainDone = elapsed >= GRAPH_MS + 900;
  const stayDone = elapsed >= 3200;
  const list = [
    booking(
      "b1",
      "transport",
      trainDone ? "confirmed" : elapsed >= 600 ? "running" : "pending",
      trainDone ? { confirmation_ref: "PKP-7Q4X-2291" } : {},
    ),
    booking(
      "b2",
      "stay",
      stayDone ? "confirmed" : elapsed >= 900 ? "approved" : "pending",
      stayDone ? { confirmation_ref: "HTL-88213" } : {},
    ),
  ];
  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      <BookingsList trip={bookings(trainDone && stayDone ? "booked" : "booking", list)} />
      <AgentRunGraph
        graph={DEMO_RAIL_GRAPH}
        steps={steps}
        title="EC 131 Warszawa → Praha · 6 passengers"
      />
    </div>
  );
}

const SHARE_DELTA = 4_000;

/** 6 · Disruption: the alert shakes in, the old ticket is stamped, the new one slides in. */
export function DisruptionScene(): ReactNode {
  const elapsed = useSceneClock(7000);
  const stage = cueIndex([900, 3800], elapsed);
  const status = stage === 0 ? "booked" : stage === 1 ? "rebooking" : "booked";
  const old = booking("b1", "transport", stage === 0 ? "confirmed" : "cancelled", {
    confirmation_ref: "PKP-7Q4X-2291",
  });
  const replacement = booking("b3", "transport", stage === 2 ? "confirmed" : "running", {
    replaces_booking_id: "b1",
    ...(stage === 2 ? { confirmation_ref: "PKP-9M2C-5530" } : {}),
  });
  const list = stage === 0 ? [old] : [replacement, old];
  const shares = contributions(6).map((share) => ({
    user_id: share.user_id,
    display_name: share.display_name,
    previous_minor: share.amount_minor,
    share_minor: share.amount_minor + SHARE_DELTA,
    delta_minor: SHARE_DELTA,
    paid_minor: share.paid_minor,
    status: "pending" as const,
  }));
  return (
    <div className="space-y-4">
      <Panel className="px-2 py-5 sm:px-6 sm:py-6">
        <StatusStepper status={status} />
      </Panel>
      {stage >= 1 && (
        <DisruptionAlert
          replacements={1}
          totalMinor={355_800 + SHARE_DELTA * 6}
          previousTotalMinor={355_800}
          shares={shares.slice(0, 3)}
          currency={CURRENCY}
        />
      )}
      <BookingsList trip={bookings(status, list)} />
    </div>
  );
}

const FEED_CUES = [0, 700, 1400, 2600, 3500, 4300];

/** 7 · Feed: members slide in from the left, the agent types before it speaks. */
export function FeedScene(): ReactNode {
  const elapsed = useSceneClock(6500);
  const events = FEED.slice(0, cueIndex(FEED_CUES, elapsed));
  return (
    <Panel className="mx-auto max-w-xl">
      <PanelHeader>
        <span>Group chat</span>
        <span>{events.length} messages</span>
      </PanelHeader>
      <div className="min-h-[26rem] px-4 py-4">
        <FeedList events={events} myUserId={ME} currency={CURRENCY} />
      </div>
    </Panel>
  );
}

/** 8 · Page transitions: the View Transitions cross-fade, and a button press. */
export function TransitionsScene(): ReactNode {
  const [page, setPage] = useState<"room" | "bookings">("room");
  useEffect(() => {
    const timer = window.setInterval(() => {
      withViewTransition(() => setPage((value) => (value === "room" ? "bookings" : "room")));
    }, 1600);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className="space-y-4">
      <Panel className="p-6 sm:p-8">
        <p className="eyebrow">{page === "room" ? "/t/prague" : "/t/prague/bookings"}</p>
        <h3 className="display mt-3 text-5xl text-ink">
          {page === "room" ? "Prague in December" : "Bookings"}
        </h3>
        <p className="mt-2 text-muted">
          {page === "room"
            ? "The room: chat, packages and shares."
            : "The agent buys each part of the trip on the supplier's site."}
        </p>
      </Panel>
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={() =>
            withViewTransition(() => setPage((value) => (value === "room" ? "bookings" : "room")))
          }
        >
          Switch page
          <ArrowRight className="size-4" aria-hidden />
        </Button>
        <Button variant="lime">Press me</Button>
        <Button variant="outline">And me</Button>
      </div>
    </div>
  );
}
