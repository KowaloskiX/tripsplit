import { type ReactNode, useEffect, useMemo, useRef } from "react";

import { Panel, PanelHeader } from "@/components/ui/panel";
import { SpeakerToggle, type Spoken, useSpeakArrivals } from "@/features/voice";

import { AGENT_TYPING_MS, FeedList, isConversation } from "./feed-list";
import { MessageInput } from "./message-input";
import { useFeed } from "./queries";

type TripFeedProps = {
  tripId: string;
  myUserId: string;
  currency?: string;
};

export function TripFeed({ tripId, myUserId, currency }: TripFeedProps): ReactNode {
  const { data: feed, isPending } = useFeed(tripId);
  const events = useMemo(() => (feed ?? []).filter(isConversation), [feed]);
  const scroller = useRef<HTMLDivElement>(null);
  // New agent messages are read aloud when unmuted; the history loaded with the page is not.
  const agentSays = useMemo(
    () =>
      isPending
        ? null
        : events
            .filter((event) => event.actor === "agent" && event.message)
            .map((event) => ({ id: event.id, text: event.message })),
    [events, isPending],
  );

  // Keep the newest message in view — a chat that does not follow new messages feels broken.
  const count = events.length;
  useEffect(() => {
    const element = scroller.current;
    if (!element || count === 0) return;
    element.scrollTop = element.scrollHeight;
    // Again once a typing agent's message has replaced its dots (it is taller).
    const timer = window.setTimeout(
      () => element.scrollTo({ top: element.scrollHeight, behavior: "smooth" }),
      AGENT_TYPING_MS + 50,
    );
    return () => window.clearTimeout(timer);
  }, [count]);

  return (
    <Panel className="flex h-[min(70dvh,640px)] flex-col overflow-hidden shadow-none">
      <PanelHeader>
        <span>Group chat</span>
        {agentSays && <AgentVoice messages={agentSays} />}
      </PanelHeader>
      <div ref={scroller} className="flex-1 overflow-y-auto px-4 py-4">
        {isPending ? (
          <p className="py-8 text-center text-sm text-muted">Loading…</p>
        ) : (
          <FeedList events={events} myUserId={myUserId} {...(currency ? { currency } : {})} />
        )}
      </div>
      <div className="border-t border-line bg-surface p-3">
        <MessageInput tripId={tripId} />
      </div>
    </Panel>
  );
}

/** Mounted once the feed has loaded, so the first batch counts as history, not as arrivals. */
function AgentVoice({ messages }: { messages: readonly Spoken[] }): ReactNode {
  const speech = useSpeakArrivals(messages);
  return <SpeakerToggle speech={speech} className="-my-1.5" />;
}
