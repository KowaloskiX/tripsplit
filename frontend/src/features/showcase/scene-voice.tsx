import { type ReactNode, useEffect, useState } from "react";

import { QuickPlan, type QuickPlanStage } from "@/features/quick-plan";
import { MicOrb, useSpeechRecognitionSupported } from "@/features/voice";

import { CURRENCY } from "./fixtures";
import { quickPackages } from "./fixtures-live";
import { cueIndex, useSceneClock } from "./timeline";

const SAID = [
  "Praga,",
  "od czwartego",
  "do szóstego grudnia,",
  "sześć osób,",
  "siedemset",
  "złotych na głowę",
];
const WORD_CUES = [600, 1100, 1700, 2300, 2800, 3200];
const FINAL_AT = 4400;
const ANSWER_AT = 6200;
const REPLY = "Praga for six, 4–6 December: three ways under 700 zł each. Swipe, then take one.";

/** Voice · a scripted utterance streams in, submits on silence, and the agent answers aloud. */
export function VoiceScene(): ReactNode {
  const elapsed = useSceneClock(8000);
  const live = useSpeechRecognitionSupported();
  const words = cueIndex(WORD_CUES, elapsed);
  const listening = words > 0 && elapsed < FINAL_AT;
  // A word just arrived → loud; then it sinks until the next one.
  const sinceWord = elapsed - (WORD_CUES[words - 1] ?? 0);
  const level = listening ? Math.max(0.2, 0.95 - sinceWord / 600) : 0;
  const transcript = SAID.slice(0, words).join(" ");

  const [asked, setAsked] = useState<string | null>(null);
  const [askedThinking, setAskedThinking] = useState(false);
  useEffect(() => {
    if (!askedThinking) return;
    const timer = window.setTimeout(() => setAskedThinking(false), 1500);
    return () => window.clearTimeout(timer);
  }, [askedThinking]);

  const scripted: QuickPlanStage =
    elapsed < FINAL_AT ? "idle" : elapsed < ANSWER_AT ? "thinking" : "answered";
  const stage: QuickPlanStage = asked ? (askedThinking ? "thinking" : "answered") : scripted;

  return (
    <div className="space-y-5">
      {stage === "idle" && (
        <div className="flex flex-col items-center gap-3" aria-live="polite">
          <MicOrb listening={listening} level={level} />
          <p className="min-h-7 max-w-xl text-center text-lg text-ink">
            {transcript || (
              <span className="text-muted">Tap the mic and say where, when, who…</span>
            )}
            {listening && (
              <span className="caret ml-0.5 inline-block h-5 w-[2px] translate-y-1 bg-lime" />
            )}
          </p>
          <p className="ticket-mono text-[11px] uppercase text-muted">
            simulated transcript · pl-PL
          </p>
        </div>
      )}
      <QuickPlan
        stage={stage}
        prompt={asked ?? (elapsed >= FINAL_AT ? transcript : null)}
        reply={asked ? `Heard you: “${asked}”. Here is what I'd book.` : REPLY}
        packages={quickPackages()}
        currency={CURRENCY}
        onSubmit={(prompt) => {
          setAsked(prompt);
          setAskedThinking(true);
        }}
      />
      <p className="ticket-mono text-center text-xs text-muted">
        {live
          ? "This browser can listen — tap the mic in the box to try it for real; unmute to hear the reply."
          : "No SpeechRecognition here (Firefox?) — the mic stays hidden; Chrome, Edge or Safari can listen."}
      </p>
    </div>
  );
}
