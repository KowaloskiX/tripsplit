import { MicOff } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useEffect } from "react";

import { cn } from "@/lib/utils";

import { LangToggle } from "./lang-toggle";
import { MicOrb } from "./mic-orb";
import { useVoiceStore } from "./store";
import { useSpeechInput } from "./use-speech-input";

const LANG_NAME = { "pl-PL": "Polish", "en-US": "English" } as const;

export const UNSUPPORTED_HINT = "Voice input needs Chrome, Edge or Safari. Type instead.";

export type MicButtonProps = {
  /** The live transcript — fill the input with it as words arrive. */
  onTranscript?: (text: string) => void;
  /** The whole utterance once listening ends — submit it. */
  onFinal?: (text: string) => void;
  /** Show the PL/EN switch next to the mic. */
  withLang?: boolean;
  size?: "md" | "lg";
  disabled?: boolean;
  className?: string;
};

/**
 * Tap to talk: listens in the chosen language (Polish by default), streams the transcript to
 * `onTranscript`, and hands the utterance to `onFinal` after a short silence. Tap again to stop
 * early (and submit), Escape to throw it away. Without SpeechRecognition (Firefox) it shrinks
 * to a quiet icon whose tooltip says why.
 */
export function MicButton({
  onTranscript,
  onFinal,
  withLang = false,
  size = "lg",
  disabled = false,
  className,
}: MicButtonProps): ReactNode {
  const lang = useVoiceStore((state) => state.lang);
  const hydrate = useVoiceStore((state) => state.hydrate);
  useEffect(() => hydrate(), [hydrate]);
  const input = useSpeechInput({ lang, onInterim: onTranscript, onFinal });

  if (!input.supported) {
    return (
      <span
        className={cn("inline-flex size-9 items-center justify-center text-muted/60", className)}
        title={UNSUPPORTED_HINT}
        role="img"
        aria-label={UNSUPPORTED_HINT}
      >
        <MicOff className="size-4" aria-hidden />
      </span>
    );
  }

  const onKeyDown = (event: KeyboardEvent): void => {
    if (event.key === "Escape" && input.listening) {
      event.preventDefault();
      input.cancel();
    }
  };

  return (
    <span className={cn("relative inline-flex items-center gap-1", className)}>
      {withLang && <LangToggle disabled={input.listening} />}
      <button
        type="button"
        onClick={input.toggle}
        onKeyDown={onKeyDown}
        disabled={disabled}
        aria-pressed={input.listening}
        aria-label={input.listening ? "Stop listening" : `Speak (${LANG_NAME[lang]})`}
        title={input.listening ? "Listening… tap to finish, Esc to cancel" : "Tap and speak"}
        className="rounded-full outline-none transition duration-150 focus-visible:ring-2 focus-visible:ring-sun active:scale-[0.95] disabled:pointer-events-none disabled:opacity-50 motion-reduce:active:scale-100"
      >
        <MicOrb listening={input.listening} level={input.level} size={size} />
      </button>
      <span className="sr-only" aria-live="polite">
        {input.listening ? "Listening" : ""}
      </span>
      {input.error && (
        <span
          role="alert"
          className="rise-in absolute top-full right-0 z-10 mt-2 w-max max-w-64 rounded-2xl bg-danger-soft px-3 py-1.5 text-xs text-danger shadow-card"
        >
          {input.error}
        </span>
      )}
    </span>
  );
}
