import { ArrowRight, ArrowUp } from "lucide-react";
import {
  type CSSProperties,
  type FormEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { MicButton } from "@/features/voice";
import {
  apiErrorMessage,
  type QuickDraftResponse,
  type QuickQuestionResponse,
  type QuickTripRequest,
} from "@/lib/api";

import { AgentMessage, TypingMessage, UserMessage } from "./chat-bubbles";
import { draftChips } from "./from-api";
import { useQuickBrief, useSay } from "./mutations";
import { AnswerChips, BriefChips } from "./step-widgets";
import { TripChat } from "./trip-chat";

export const EXAMPLE_BRIEFS = [
  "Weekend in Prague for 4, 20–22 Nov, up to 700 zł each, by train",
  "Barcelona in March for 4, by plane",
  "A cheap weekend in Kraków for 6",
] as const;

type Answers = Pick<QuickTripRequest, "destination" | "dates" | "group_size">;

type Turn =
  | { id: number; role: "user"; text: string }
  | {
      id: number;
      role: "agent";
      reply: string;
      draft: QuickDraftResponse;
      question: QuickQuestionResponse | null;
    };

/** A chip (its label -> value) or typed text, put into the field the question names. */
export function answerFor(question: QuickQuestionResponse, input: string): Answers | null {
  const value = question.options.find((option) => option.label === input)?.value ?? input.trim();
  if (!value) return null;
  if (question.field === "group_size") {
    const size = Number.parseInt(value, 10);
    return Number.isFinite(size) && size > 0 ? { group_size: size } : null;
  }
  return { [question.field]: value };
}

function Composer({
  placeholder,
  disabled,
  onSend,
}: {
  placeholder: string;
  disabled: boolean;
  onSend: (text: string) => void;
}): ReactNode {
  const [draft, setDraft] = useState("");
  const send = (text: string): void => {
    const value = text.trim();
    if (!value || disabled) return;
    onSend(value);
    setDraft("");
  };
  const onSubmit = (event: FormEvent): void => {
    event.preventDefault();
    send(draft);
  };
  return (
    <form
      onSubmit={onSubmit}
      className="sticky bottom-0 z-10 -mx-4 bg-gradient-to-t from-bg via-bg/95 to-transparent px-4 pt-6 pb-4 sm:mx-0 sm:px-0"
    >
      <div className="flex items-center gap-2 rounded-full border border-ink/15 bg-surface p-1.5 pl-5 shadow-card focus-within:border-ink/40">
        <label htmlFor="chat-composer" className="sr-only">
          Message
        </label>
        <input
          id="chat-composer"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={placeholder}
          className="min-w-0 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-muted"
        />
        <MicButton withLang onTranscript={setDraft} onFinal={send} />
        <Button type="submit" size="icon" aria-label="Send" disabled={!draft.trim() || disabled}>
          <ArrowUp className="size-5" aria-hidden />
        </Button>
      </div>
    </form>
  );
}

const NEAR_BOTTOM_PX = 320;
const HEADER_ROOM_PX = 140;

/** Keeps the newest message in view as the thread grows — unless the user scrolled up. */
function useStickToBottom(): React.RefObject<HTMLDivElement | null> {
  const thread = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const node = thread.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    let last = node.scrollHeight;
    const observer = new ResizeObserver(() => {
      const before = last;
      last = node.scrollHeight;
      if (last <= before) return;
      const viewportBottom = window.scrollY + window.innerHeight;
      const oldEnd = node.getBoundingClientRect().top + window.scrollY + before;
      // Only follow when the reader was at the end of the thread, not reading back.
      if (oldEnd - viewportBottom > NEAR_BOTTOM_PX) return;
      const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
      // The new message's top lands just under the header (or the page simply ends).
      const target = Math.min(oldEnd - HEADER_ROOM_PX, maxScroll);
      if (target > window.scrollY) window.scrollTo({ top: target, behavior: "smooth" });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return thread;
}

type ChatFlowProps = {
  tripId?: string | undefined;
  /** The brief became a trip: put it in the URL so a reload resumes it. */
  onTrip: (tripId: string) => void;
  onOpenRoom: (tripId: string) => void;
};

/**
 * The whole trip as one chat at `/plan`: the brief (with chips for anything missing), the
 * live search, transport -> stay -> activities picked one at a time, the summary, who pays,
 * and the agent booking it — every step a message, every choice the user's reply.
 */
export function ChatFlow({ tripId, onTrip, onOpenRoom }: ChatFlowProps): ReactNode {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [answers, setAnswers] = useState<Answers>({});
  const quick = useQuickBrief();
  const say = useSay(tripId ?? "");
  const thread = useStickToBottom();

  const brief = turns
    .filter((turn): turn is Extract<Turn, { role: "user" }> => turn.role === "user")
    .map((turn) => turn.text)
    .join("\n");
  const lastAgent = [...turns].reverse().find((turn) => turn.role === "agent");
  const question = lastAgent?.role === "agent" ? lastAgent.question : null;

  const ask = (text: string, next: Answers, userText: string): void => {
    const id = turns.length;
    setTurns((current) => [...current, { id, role: "user", text: userText }]);
    quick.mutate(
      { body: { text, ...next } },
      {
        onSuccess: (response) => {
          setTurns((current) => [
            ...current,
            {
              id: id + 1,
              role: "agent",
              reply: response.reply,
              draft: response.draft,
              question: response.trip ? null : (response.questions[0] ?? null),
            },
          ]);
          if (response.trip) onTrip(response.trip.trip_id);
        },
      },
    );
  };

  const send = (text: string): void => {
    if (tripId) {
      say.mutate({ path: { trip_id: tripId }, body: { text } });
      return;
    }
    if (question) {
      const value = answerFor(question, text);
      if (value) {
        const next = { ...answers, ...value };
        setAnswers(next);
        ask(brief, next, text);
        return;
      }
    }
    ask(brief ? `${brief}\n${text}` : text, answers, text);
  };

  const answer = (option: string): void => {
    if (!question) return;
    const value = answerFor(question, option);
    if (!value) return;
    const next = { ...answers, ...value };
    setAnswers(next);
    ask(brief, next, option);
  };

  const fresh = !tripId && turns.length === 0;
  return (
    <div className="mx-auto flex min-h-[calc(100dvh-9rem)] w-full max-w-3xl flex-col">
      {fresh && (
        <div className="mt-[8vh] mb-8 space-y-6 text-center">
          <h1 className="display text-[clamp(2.2rem,6vw,3.8rem)] text-balance text-ink">
            Where are we going?
          </h1>
          <p className="text-muted">
            Tell me in one sentence. I'll find the trains or flights, a place to stay and things to
            do — you pick, step by step.
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            {EXAMPLE_BRIEFS.map((example, index) => (
              <button
                key={example}
                type="button"
                onClick={() => send(example)}
                className="rise-in rounded-full bg-surface-sunken px-3.5 py-1.5 text-sm text-muted transition hover:text-ink active:scale-[0.97]"
                style={{ "--i": index, "--delay": "150ms" } as CSSProperties}
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      )}

      <div ref={thread} className="flex-1 space-y-4" aria-live="polite">
        {turns.map((turn) =>
          turn.role === "user" ? (
            <UserMessage key={turn.id}>{turn.text}</UserMessage>
          ) : (
            <AgentMessage key={turn.id} text={turn.reply} wide>
              {!tripId && (
                <>
                  <BriefChips chips={draftChips(turn.draft)} />
                  {turn === lastAgent && turn.question && (
                    <div className="space-y-2">
                      <p className="text-sm text-ink">{turn.question.question}</p>
                      <AnswerChips
                        options={turn.question.options.map((option) => option.label)}
                        onAnswer={answer}
                      />
                    </div>
                  )}
                </>
              )}
            </AgentMessage>
          ),
        )}
        {quick.isPending && <TypingMessage label="The agent is reading your brief" />}
        {quick.error && <ErrorCallout>{apiErrorMessage(quick.error)}</ErrorCallout>}
        {tripId && (
          <TripChat
            tripId={tripId}
            showBrief={turns.length === 0}
            onOpenRoom={() => onOpenRoom(tripId)}
          />
        )}
        {say.error && <ErrorCallout>{apiErrorMessage(say.error)}</ErrorCallout>}
      </div>

      {tripId && (
        <div className="flex justify-center pt-4">
          <Button size="sm" variant="ghost" onClick={() => onOpenRoom(tripId)}>
            Open trip room
            <ArrowRight className="size-4" aria-hidden />
          </Button>
        </div>
      )}
      <Composer
        placeholder={
          tripId
            ? "Message the group…"
            : question
              ? "Type an answer…"
              : "Prague, 20–22 Nov, 4 people, 700 zł each"
        }
        disabled={quick.isPending || say.isPending}
        onSend={send}
      />
    </div>
  );
}
