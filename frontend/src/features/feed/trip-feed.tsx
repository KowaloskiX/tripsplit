import { type ReactNode, useEffect, useRef } from "react";

import { Panel, PanelHeader } from "@/components/ui/panel";

import { FeedList } from "./feed-list";
import { MessageInput } from "./message-input";
import { useFeed } from "./queries";

type TripFeedProps = {
  tripId: string;
  myUserId: string;
  currency?: string;
};

export function TripFeed({ tripId, myUserId, currency }: TripFeedProps): ReactNode {
  const { data: events = [], isPending } = useFeed(tripId);
  const scroller = useRef<HTMLDivElement>(null);

  // Keep the newest message in view — a chat that does not follow new messages feels broken.
  const count = events.length;
  useEffect(() => {
    const element = scroller.current;
    if (element && count > 0) element.scrollTop = element.scrollHeight;
  }, [count]);

  return (
    <Panel className="flex h-[min(72dvh,720px)] flex-col overflow-hidden">
      <PanelHeader>
        <span>Group chat</span>
        <span>{events.length} messages</span>
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
