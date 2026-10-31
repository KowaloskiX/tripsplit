import { type ReactNode, useReducer, useState } from "react";

import { ErrorCallout } from "@/components/ui/callout";
import { useTripBookings } from "@/features/bookings";
import { TravellerDetailsPanel } from "@/features/travellers";
import { useRoom } from "@/features/trips";
import {
  apiErrorMessage,
  type OptionResponse,
  type RoomResponse,
  type TripOptionsResponse,
} from "@/lib/api";
import { formatMoney } from "@/lib/money";

import { BookingStep } from "./booking-step";
import { AgentMessage, GroupBubble, TypingMessage, UserMessage } from "./chat-bubbles";
import { changesLabel, groupMessages, optionLegs, supplierTicks, tripChips } from "./from-api";
import {
  answeredSteps,
  type ChatAction,
  type ChatState,
  chatReducer,
  INITIAL_CHAT,
  type Offered,
  type PickStep,
  pickingStep,
  type TripPhase,
  tripPhase,
} from "./model";
import { useSelectOptions } from "./mutations";
import { ActivityPicker, StayCard, TransportCard } from "./option-cards";
import { useTripFeed, useTripOptions } from "./queries";
import { BriefChips, SummaryCard, type SummaryLine, SupplierTicks } from "./step-widgets";
import { type WhoPays, WhoPaysStep } from "./who-pays";

const SHOWN_TRANSPORT = 4;
const SHOWN_STAYS = 5;

const QUESTION: Record<PickStep, string> = {
  transport: "How do you want to get there?",
  stay: "Where do you want to stay?",
  activities: "Anything to do while you're there?",
};

function find(options: readonly OptionResponse[], id: string | null): OptionResponse | undefined {
  return options.find((option) => option.option_id === id);
}

function transportAnswer(option: OptionResponse, currency: string): string {
  const leg = optionLegs(option)[0];
  const when = leg ? ` · ${leg.departs} · ${changesLabel(leg.changes)}` : "";
  return `${option.label}${when} · ${formatMoney(option.per_person_minor, currency)} pp`;
}

function answerText(
  step: PickStep,
  state: ChatState,
  options: TripOptionsResponse,
  currency: string,
): string {
  if (step === "transport") {
    const option = find(options.transport, state.picks.transport);
    return option ? transportAnswer(option, currency) : "";
  }
  if (step === "stay") {
    const option = find(options.stays, state.picks.stay);
    return option ? `${option.label} · ${formatMoney(option.per_person_minor, currency)} pp` : "";
  }
  const picked = (state.picks.activities ?? []).flatMap((id) => {
    const option = find(options.activities, id);
    return option ? [option.label] : [];
  });
  return picked.length ? picked.join(", ") : "Nothing for now, thanks";
}

function PickWidget({
  step,
  state,
  options,
  currency,
  dispatch,
}: {
  step: PickStep;
  state: ChatState;
  options: TripOptionsResponse;
  currency: string;
  dispatch: (action: ChatAction) => void;
}): ReactNode {
  if (step === "transport") {
    return (
      <ul className="grid gap-2" aria-label="Ways to get there">
        {options.transport.slice(0, SHOWN_TRANSPORT).map((option, index) => (
          <TransportCard
            key={option.option_id}
            option={option}
            currency={currency}
            index={index}
            picked={state.picks.transport === option.option_id}
            onPick={(id) => dispatch({ type: "pick_transport", id })}
          />
        ))}
      </ul>
    );
  }
  if (step === "stay") {
    return (
      <ul
        aria-label="Places to stay"
        className="-mr-4 flex snap-x snap-mandatory items-start gap-3 overflow-x-auto pr-4 pb-2 sm:-mr-6 sm:pr-6"
      >
        {options.stays.slice(0, SHOWN_STAYS).map((option, index) => (
          <StayCard
            key={option.option_id}
            option={option}
            currency={currency}
            index={index}
            picked={state.picks.stay === option.option_id}
            onPick={(id) => dispatch({ type: "pick_stay", id })}
          />
        ))}
      </ul>
    );
  }
  return (
    <ActivityPicker
      options={options.activities}
      currency={currency}
      initial={state.picks.activities ?? []}
      onDone={(ids) => dispatch({ type: "set_activities", ids })}
    />
  );
}

function pickedLines(state: ChatState, options: TripOptionsResponse): SummaryLine[] {
  const picked = [
    find(options.transport, state.picks.transport),
    find(options.stays, state.picks.stay),
    ...(state.picks.activities ?? []).map((id) => find(options.activities, id)),
  ];
  return picked.flatMap((option) =>
    option ? [{ id: option.option_id, label: option.label, totalMinor: option.total_minor }] : [],
  );
}

/** Steps 3–6: transport, stay, activities, then the summary that locks the package in. */
function Picking({
  room,
  options,
  state,
  dispatch,
}: {
  room: RoomResponse;
  options: TripOptionsResponse;
  state: ChatState;
  dispatch: (action: ChatAction) => void;
}): ReactNode {
  const select = useSelectOptions(room.trip.id);
  const currency = room.trip.currency;
  const offered: Offered = {
    transport: options.transport.length,
    stays: options.stays.length,
    activities: options.activities.length,
  };
  const active = pickingStep(state, offered);
  const answered = answeredSteps(state, offered);
  const organizer = room.my_role === "organizer";

  if (!organizer) {
    return <AgentMessage text="The organizer is picking the trip — you'll see it here." />;
  }
  const confirm = (): void => {
    if (!state.picks.transport) return;
    select.mutate({
      path: { trip_id: room.trip.id },
      body: {
        transport_option_id: state.picks.transport,
        stay_option_id: state.picks.stay,
        activity_option_ids: (state.picks.activities ?? []).join(","),
      },
    });
  };
  return (
    <>
      {answered.map((step) => (
        <div key={step} className="space-y-3">
          <AgentMessage text={QUESTION[step]} />
          <UserMessage onChange={() => dispatch({ type: "edit", step })}>
            {answerText(step, state, options, currency)}
          </UserMessage>
        </div>
      ))}
      {active !== "summary" ? (
        <AgentMessage text={QUESTION[active]} wide label={QUESTION[active]}>
          <PickWidget
            step={active}
            state={state}
            options={options}
            currency={currency}
            dispatch={dispatch}
          />
        </AgentMessage>
      ) : (
        <AgentMessage text="Here's your trip. Shall I lock it in?" wide label="Summary">
          <SummaryCard
            lines={pickedLines(state, options)}
            travellers={options.travellers}
            currency={currency}
            budgetMinor={room.trip.budget_per_person_minor}
            pending={select.isPending}
            onConfirm={confirm}
            onChange={(step) => dispatch({ type: "edit", step })}
          />
          {select.error && <ErrorCallout>{apiErrorMessage(select.error)}</ErrorCallout>}
        </AgentMessage>
      )}
    </>
  );
}

function ChosenSummary({ room }: { room: RoomResponse }): ReactNode {
  const chosen = room.proposals.find((proposal) => proposal.chosen);
  if (!chosen) return null;
  return (
    <AgentMessage text={`Locked in: ${chosen.title}.`} wide label="Your trip">
      <SummaryCard
        lines={chosen.items.map((item, index) => ({
          id: `${index}`,
          label: item.title,
          totalMinor: item.price_minor,
        }))}
        travellers={Math.max(room.trip.group_size, room.members.length)}
        currency={room.trip.currency}
        budgetMinor={room.trip.budget_per_person_minor}
        pending={false}
      />
    </AgentMessage>
  );
}

function foundLine(options: TripOptionsResponse | undefined): string {
  if (!options) return "Done searching.";
  const parts = [
    `${options.transport.length} way${options.transport.length === 1 ? "" : "s"} to get there`,
    `${options.stays.length} stay${options.stays.length === 1 ? "" : "s"}`,
  ];
  if (options.activities.length) parts.push(`${options.activities.length} things to do`);
  return `Found ${parts.join(", ")}. Let's pick step by step.`;
}

const AFTER_PICK: ReadonlySet<TripPhase> = new Set(["who", "booking", "approve", "booked"]);

/**
 * The trip as one conversation, from the brief to the tickets. Server state (status, shares,
 * bookings, the feed) decides the phase; the organizer's picks live here until the package
 * exists. Every earlier step stays in the thread.
 */
export function TripChat({
  tripId,
  showBrief,
  onOpenRoom,
}: {
  tripId: string;
  /** False when the brief conversation is already on screen above. */
  showBrief: boolean;
  onOpenRoom: () => void;
}): ReactNode {
  const room = useRoom(tripId).data;
  const feed = useTripFeed(tripId).data;
  const bookings = useTripBookings(tripId).data;
  const [state, dispatch] = useReducer(chatReducer, INITIAL_CHAT);
  const [who, setWho] = useState<WhoPays | null>(null);
  const phase = room
    ? tripPhase({ status: room.trip.status, bookings: bookings?.bookings ?? [] })
    : "searching";
  const options = useTripOptions(tripId, room !== undefined && phase !== "searching");

  if (!room) return <TypingMessage label="Opening your trip" />;
  const events = feed ?? [];
  const ticks = supplierTicks(events);
  const searching = phase === "searching";
  const group = groupMessages(events, room.my_user_id);
  const me = room.members.find((member) => member.user_id === room.my_user_id);
  const detailsMissing = me !== undefined && !me.traveller_details_complete;
  const paidAll =
    room.contributions.length > 0 && room.contributions.every((c) => c.outstanding_minor === 0);

  return (
    <>
      {showBrief && room.trip.brief && <UserMessage>{room.trip.brief}</UserMessage>}
      <AgentMessage
        text={showBrief ? "Got it. Here's what I understood:" : undefined}
        continued={!showBrief}
        wide
        label="Brief"
      >
        <BriefChips chips={tripChips(room.trip)} />
      </AgentMessage>
      <AgentMessage
        text={searching ? "Searching suppliers for you…" : foundLine(options.data)}
        wide
        label="Search"
      >
        <SupplierTicks ticks={ticks} searching={searching} />
      </AgentMessage>

      {phase === "picking" && options.data && (
        <Picking room={room} options={options.data} state={state} dispatch={dispatch} />
      )}
      {phase === "picking" && options.isLoading && <TypingMessage label="Loading options" />}
      {phase === "picking" && options.error && (
        <AgentMessage text="I couldn't load the options one by one — the trip room has the ready-made packages.">
          <button type="button" className="text-sm text-ink underline" onClick={onOpenRoom}>
            Open trip room
          </button>
        </AgentMessage>
      )}

      {AFTER_PICK.has(phase) && <ChosenSummary room={room} />}
      {AFTER_PICK.has(phase) && phase !== "booked" && detailsMissing && (
        <AgentMessage
          text="Before I can buy the tickets I need your details as they appear on your ID."
          wide
          label="Your details"
        >
          <TravellerDetailsPanel room={room} embedded />
        </AgentMessage>
      )}
      {phase === "who" && !detailsMissing && (
        <AgentMessage
          text="Who's coming? I can split it with your friends, or you cover everyone now."
          wide
          label="Who pays"
        >
          <WhoPaysStep room={room} choice={who} onChoose={setWho} />
        </AgentMessage>
      )}
      {AFTER_PICK.has(phase) && phase !== "who" && paidAll && (
        <AgentMessage text="Every share is paid and held by our payment partner ✓" />
      )}

      {group.map((message) => (
        <GroupBubble key={message.id} {...message} />
      ))}

      {(phase === "booking" || phase === "approve" || phase === "booked") && (
        <BookingStep tripId={tripId} title={room.trip.title} />
      )}
      {phase === "stopped" && (
        <AgentMessage text={`This trip is ${room.trip.status}. The trip room has the details.`}>
          <button type="button" className="text-sm text-ink underline" onClick={onOpenRoom}>
            Open trip room
          </button>
        </AgentMessage>
      )}
    </>
  );
}
