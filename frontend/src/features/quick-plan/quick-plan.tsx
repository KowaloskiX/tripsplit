import { ArrowUp, Sparkles } from "lucide-react";
import { type CSSProperties, type FormEvent, type ReactNode, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { TypingIndicator } from "@/components/ui/typing-indicator";
import { MicButton, SpeakerToggle, useSpeakArrivals } from "@/features/voice";

import { ChoiceSheet } from "./choice-sheet";
import {
  type ClarifyingQuestion,
  EXAMPLE_PROMPTS,
  type PaymentChoice,
  type QuickPackage,
  type QuickPlanStage,
} from "./model";
import { QuickPackageCard } from "./quick-package-card";

export type QuickPlanProps = {
  stage: QuickPlanStage;
  /** What the user asked; shown as their bubble. */
  prompt: string | null;
  /** What the user typed after the agent's replies, oldest first; one bubble each. */
  followUps?: readonly string[];
  /** The agent's answer above the packages. */
  reply?: string;
  packages: readonly QuickPackage[];
  question?: ClarifyingQuestion | null;
  /** The package taken, once `stage` is "choosing". */
  takenId?: string | null;
  people?: number;
  currency?: string;
  examples?: readonly string[];
  onSubmit?: (prompt: string) => void;
  onAnswer?: (questionId: string, option: string) => void;
  onTake?: (packageId: string) => void;
  onChoose?: (choice: PaymentChoice) => void;
};

function AgentBubble({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="feed-in-right flex items-start gap-2.5">
      <span className="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-agent-bg text-agent-tag ring-1 ring-line">
        <Sparkles className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 max-w-[88%] rounded-3xl rounded-tl-md bg-agent-bg px-4 py-3 text-agent-fg ring-1 ring-line">
        {children}
      </div>
    </div>
  );
}

/**
 * "Plan a trip", chat first: one big question, example chips, the agent typing, then three
 * packages in a swipeable carousel, a clarifying question and the who-pays choice.
 */
export function QuickPlan({
  stage,
  prompt,
  followUps = [],
  reply = "Here are three ways to do it. Swipe, then take one.",
  packages,
  question,
  takenId,
  people = 6,
  currency = "PLN",
  examples = EXAMPLE_PROMPTS,
  onSubmit,
  onAnswer,
  onTake,
  onChoose,
}: QuickPlanProps): ReactNode {
  const [draft, setDraft] = useState("");
  const taken = packages.find((pkg) => pkg.id === takenId);
  const submit = (text: string): void => {
    const value = text.trim();
    if (!value) return;
    onSubmit?.(value);
    setDraft("");
  };
  // The agent's answer is read aloud (when unmuted) the moment it appears, never on reload.
  const answered = (stage === "answered" || stage === "choosing") && prompt !== null;
  const spoken = useMemo(
    () => (answered ? [{ id: `${prompt}\u0000${reply}`, text: reply }] : []),
    [answered, prompt, reply],
  );
  const speech = useSpeakArrivals(spoken);
  const onForm = (event: FormEvent): void => {
    event.preventDefault();
    submit(draft);
  };

  return (
    <div className="space-y-6">
      {stage === "idle" && (
        <div className="mx-auto max-w-2xl space-y-4 text-center">
          <h2 className="display text-[clamp(2.4rem,7vw,4.2rem)] text-balance text-ink">
            Where are we going?
          </h2>
        </div>
      )}

      {prompt && (
        <div className="mx-auto max-w-2xl space-y-4" aria-live="polite">
          <p className="feed-in-right ml-auto w-fit max-w-[85%] rounded-3xl rounded-br-md bg-pastel-sea px-4 py-2.5 text-[15px] text-pastel-ink">
            {prompt}
          </p>
          {followUps.map((text, index) => (
            <p
              // biome-ignore lint/suspicious/noArrayIndexKey: append-only — a bubble's position is its identity.
              key={index}
              className="feed-in-right ml-auto w-fit max-w-[85%] rounded-3xl rounded-br-md bg-pastel-sea px-4 py-2.5 text-[15px] text-pastel-ink"
            >
              {text}
            </p>
          ))}
          {stage === "thinking" && (
            <AgentBubble>
              <span className="inline-flex h-5 items-center text-agent-tag">
                <TypingIndicator />
                <span className="sr-only">The agent is looking for packages</span>
              </span>
            </AgentBubble>
          )}
          {(stage === "answered" || stage === "choosing") && (
            <AgentBubble>
              <p className="text-[15px] leading-relaxed">{reply}</p>
              {question && (
                <div className="mt-3">
                  <p className="text-sm text-agent-fg/75">{question.text}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {question.options.map((option, index) => (
                      <button
                        key={option}
                        type="button"
                        onClick={() => onAnswer?.(question.id, option)}
                        className="pop ticket-mono rounded-full border border-line bg-surface px-3 py-1 text-xs text-agent-fg transition duration-150 hover:border-ink/30 hover:text-ink active:scale-[0.97]"
                        style={{ "--i": index, "--delay": "300ms" } as CSSProperties}
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </AgentBubble>
          )}
        </div>
      )}

      {(stage === "answered" || stage === "choosing") && packages.length > 0 && (
        <ul
          aria-label="Packages"
          className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-3 sm:mx-0 sm:px-0 lg:justify-center"
        >
          {packages.map((pkg, index) => (
            <li key={pkg.id} className="contents">
              <QuickPackageCard pkg={pkg} currency={currency} index={index} onTake={onTake} />
            </li>
          ))}
        </ul>
      )}

      {stage === "choosing" && taken && (
        <div className="mx-auto max-w-2xl">
          <ChoiceSheet pkg={taken} currency={currency} people={people} onChoose={onChoose} />
        </div>
      )}

      {(stage === "idle" || stage === "answered") && (
        <form onSubmit={onForm} className="mx-auto max-w-2xl space-y-3">
          <div className="flex items-center gap-2 rounded-[var(--radius-panel)] border border-line bg-surface p-1.5 pl-5 shadow-card focus-within:border-ink/30">
            <label htmlFor="quick-plan-input" className="sr-only">
              Where, when, how many, budget?
            </label>
            <input
              id="quick-plan-input"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={
                stage === "idle" ? "Prague, 4–6 Dec, 6 people, 700 zł each" : "Ask for changes…"
              }
              className="min-w-0 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-muted sm:text-lg"
            />
            <SpeakerToggle speech={speech} />
            <MicButton withLang onTranscript={setDraft} onFinal={submit} />
            <Button type="submit" size="icon" aria-label="Plan it" disabled={!draft.trim()}>
              <ArrowUp className="size-5" aria-hidden />
            </Button>
          </div>
          {stage === "idle" && (
            <div className="flex flex-wrap justify-center gap-2">
              {examples.map((example, index) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => submit(example)}
                  className="rise-in rounded-[var(--radius-control)] border border-line bg-surface px-3.5 py-1.5 text-sm text-muted transition duration-150 hover:border-ink/25 hover:text-ink active:scale-[0.98]"
                  style={{ "--i": index, "--delay": "200ms" } as CSSProperties}
                >
                  {example}
                </button>
              ))}
            </div>
          )}
        </form>
      )}
    </div>
  );
}
