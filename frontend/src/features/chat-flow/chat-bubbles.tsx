import { Pencil, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { TypingIndicator } from "@/components/ui/typing-indicator";
import { cn } from "@/lib/utils";

/** The agent speaking: avatar left, a calm card; widgets go in `children` under the text. */
export function AgentMessage({
  text,
  children,
  wide = false,
  label,
}: {
  text?: ReactNode;
  children?: ReactNode;
  /** Widgets such as a row of cards need the full width. */
  wide?: boolean;
  label?: string;
}): ReactNode {
  return (
    <section aria-label={label} className="feed-in-right flex items-start gap-2.5">
      <span className="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-agent-bg text-agent-tag ring-1 ring-line">
        <Sparkles className="size-4" aria-hidden />
      </span>
      <div className={cn("min-w-0 space-y-3", wide ? "flex-1" : "max-w-[88%]")}>
        {text && (
          <div className="w-fit max-w-full rounded-3xl rounded-tl-md bg-agent-bg px-4 py-3 text-[15px] leading-relaxed text-agent-fg ring-1 ring-line">
            {text}
          </div>
        )}
        {children}
      </div>
    </section>
  );
}

/** The user's answer, right-aligned; "change" reopens the step it answered. */
export function UserMessage({
  children,
  onChange,
}: {
  children: ReactNode;
  onChange?: (() => void) | undefined;
}): ReactNode {
  return (
    <div className="feed-in-right flex flex-col items-end gap-1">
      <div className="w-fit max-w-[85%] rounded-3xl rounded-br-md bg-pastel-sea px-4 py-2.5 text-[15px] text-pastel-ink">
        {children}
      </div>
      {onChange && (
        <button
          type="button"
          onClick={onChange}
          className="inline-flex items-center gap-1 px-2 text-xs text-muted transition hover:text-ink"
        >
          <Pencil className="size-3" aria-hidden />
          change
        </button>
      )}
    </div>
  );
}

export function TypingMessage({ label }: { label: string }): ReactNode {
  return (
    <AgentMessage
      text={
        <span className="inline-flex h-5 items-center text-agent-tag">
          <TypingIndicator />
          <span className="sr-only">{label}</span>
        </span>
      }
    />
  );
}

/** A friend (or the agent, about the group) in the same thread. */
export function GroupBubble({
  author,
  text,
  mine,
  tone,
}: {
  author: string | null;
  text: string;
  mine: boolean;
  tone: "info" | "warn";
}): ReactNode {
  if (mine) return <UserMessage>{text}</UserMessage>;
  if (author === null && tone === "info") return <AgentMessage text={text} />;
  return (
    <div className="feed-in-right flex items-start gap-2.5">
      <span
        aria-hidden
        className="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-sunken text-xs font-medium text-muted ring-1 ring-line"
      >
        {author ? author.slice(0, 1).toUpperCase() : "·"}
      </span>
      <div
        className={cn(
          "w-fit max-w-[85%] rounded-3xl rounded-tl-md px-4 py-2.5 text-sm ring-1",
          tone === "warn" ? "bg-warn-soft text-ink ring-warn/30" : "bg-surface text-ink ring-line",
        )}
      >
        {author && <p className="text-xs font-medium text-muted">{author}</p>}
        <p>{text}</p>
      </div>
    </div>
  );
}
