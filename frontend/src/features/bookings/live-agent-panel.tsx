import { type ReactNode, useEffect, useState } from "react";

import { ErrorCallout } from "@/components/ui/callout";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { agentRunFrameUrl, apiErrorMessage, type BookingResponse } from "@/lib/api";

import { ApprovalCard } from "./approval-card";
import { MilestoneStepper } from "./milestone-stepper";
import { useApproveBooking } from "./mutations";
import { useRunStatus } from "./queries";
import { RunGraph } from "./run-graph";

const FRAME_POLL_MS = 1000;

/** A counter that ticks every second while `active` — the frame URL's cache buster. */
function useTick(active: boolean): number {
  const [tick, setTick] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setTick(Date.now()), FRAME_POLL_MS);
    return () => window.clearInterval(timer);
  }, [active]);
  return tick;
}

type LiveAgentPanelProps = {
  tripId: string;
  booking: BookingResponse;
  currency: string;
  isOrganizer: boolean;
  travellers?: number | undefined;
};

/** What the agent sees and where it is in the checkout, refreshed every second. */
export function LiveAgentPanel({
  tripId,
  booking,
  currency,
  isOrganizer,
  travellers,
}: LiveAgentPanelProps): ReactNode {
  const run = booking.run;
  const working = booking.status === "running" || booking.status === "approved";
  const tick = useTick(working);
  const status = useRunStatus(run?.run_id ?? "", working && run !== null);
  const approval = useApproveBooking(tripId);
  // The tick whose frame failed to load (no frame yet); the next tick retries.
  const [failedTick, setFailedTick] = useState<number | null>(null);

  if (!run) return null;
  const live = status.data?.live;
  const frameUrl = agentRunFrameUrl(run.run_id, tick);
  const reason = live?.reason || run.reason;

  if (booking.status === "awaiting_approval" && isOrganizer) {
    return (
      <div className="space-y-2">
        <ApprovalCard
          frameUrl={frameUrl}
          supplier={booking.supplier}
          amountMinor={booking.amount_minor}
          currency={currency}
          travellers={travellers}
          pending={approval.isPending}
          onDecision={(approved) => approval.decide(booking.id, approved)}
        />
        {approval.error && <ErrorCallout>{apiErrorMessage(approval.error)}</ErrorCallout>}
      </div>
    );
  }

  return (
    <Panel>
      <PanelHeader>
        <span>{working ? "Live · agent working" : "Agent run"}</span>
        <span>
          step {live?.step ?? run.steps}
          {run.cost_usd > 0 ? ` · $${run.cost_usd.toFixed(3)}` : ""}
        </span>
      </PanelHeader>
      <div className="space-y-3 p-4">
        <MilestoneStepper
          milestone={live?.milestone ?? run.milestone}
          finished={booking.status === "confirmed"}
        />
        <RunGraph runId={run.run_id} active={working} steps={live?.steps} title={booking.title} />
        {failedTick === tick && <p className="text-sm text-muted">Waiting for the first frame…</p>}
        <img
          src={frameUrl}
          alt={`What the agent sees on ${booking.supplier}`}
          hidden={failedTick === tick}
          className="w-full rounded-[var(--radius-control)] border border-line bg-surface-sunken"
          onError={() => setFailedTick(tick)}
        />
        {reason && working && <p className="text-sm text-muted">{reason}</p>}
        <RunNotice booking={booking} reason={reason} isOrganizer={isOrganizer} />
      </div>
    </Panel>
  );
}

function RunNotice({
  booking,
  reason,
  isOrganizer,
}: {
  booking: BookingResponse;
  reason: string;
  isOrganizer: boolean;
}): ReactNode {
  switch (booking.status) {
    case "awaiting_approval":
      return (
        <p className="text-sm text-warn">
          The summary is ready. Waiting for the organizer to approve the payment.
        </p>
      );
    case "confirmed":
      return (
        <p className="text-sm font-medium text-success">
          Confirmed{booking.confirmation_ref ? ` · booking number ${booking.confirmation_ref}` : ""}
        </p>
      );
    case "handoff":
      return (
        <p className="text-sm text-warn">
          A human needs to finish this on{" "}
          <a className="underline" href={booking.supplier_url} target="_blank" rel="noreferrer">
            {booking.supplier}
          </a>
          {reason ? `: ${reason}` : "."}
          {isOrganizer ? " You can also start the agent again." : ""}
        </p>
      );
    case "failed":
      return <ErrorCallout>The agent could not finish: {reason || "unknown error"}</ErrorCallout>;
    default:
      return null;
  }
}
