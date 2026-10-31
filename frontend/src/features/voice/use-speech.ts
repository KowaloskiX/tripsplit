import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { guessLang, pickVoice, speechSynthesisOrNull, type VoiceLang } from "./speech-api";
import { useVoiceStore } from "./store";

export const SPEECH_RATE = 1.05;

export type Speech = {
  supported: boolean;
  muted: boolean;
  toggleMuted: () => void;
  speaking: boolean;
  /** Reads `text` aloud unless muted; queued behind anything already being read. */
  speak: (text: string, lang?: VoiceLang) => boolean;
  cancel: () => void;
};

const noSubscribe = (): (() => void) => () => {};

function useSynthesisSupported(): boolean {
  return useSyncExternalStore(
    noSubscribe,
    () => speechSynthesisOrNull() !== null && typeof SpeechSynthesisUtterance !== "undefined",
    () => false,
  );
}

/** The installed voices; Chrome fills the list asynchronously and announces it. */
function useVoices(synth: SpeechSynthesis | null): readonly SpeechSynthesisVoice[] {
  const [voices, setVoices] = useState<readonly SpeechSynthesisVoice[]>([]);
  useEffect(() => {
    if (!synth) return;
    const read = (): void => setVoices(synth.getVoices());
    read();
    synth.addEventListener?.("voiceschanged", read);
    return () => synth.removeEventListener?.("voiceschanged", read);
  }, [synth]);
  return voices;
}

/** Text to speech through the browser (speechSynthesis), behind the persisted mute toggle. */
export function useSpeech(): Speech {
  const supported = useSynthesisSupported();
  const synth = supported ? speechSynthesisOrNull() : null;
  const voices = useVoices(synth);
  const muted = useVoiceStore((state) => state.muted);
  const hydrate = useVoiceStore((state) => state.hydrate);
  const toggleStoreMuted = useVoiceStore((state) => state.toggleMuted);
  const [speaking, setSpeaking] = useState(false);
  const pending = useRef(0);

  useEffect(() => hydrate(), [hydrate]);

  const cancel = useCallback((): void => {
    pending.current = 0;
    synth?.cancel();
    setSpeaking(false);
  }, [synth]);

  const speak = useCallback(
    (text: string, lang?: VoiceLang): boolean => {
      const words = text.trim();
      if (!synth || muted || !words) return false;
      const utterance = new SpeechSynthesisUtterance(words);
      utterance.lang = lang ?? guessLang(words);
      const voice = pickVoice(voices, utterance.lang);
      if (voice) utterance.voice = voice;
      utterance.rate = SPEECH_RATE;
      const done = (): void => {
        pending.current = Math.max(0, pending.current - 1);
        if (pending.current === 0) setSpeaking(false);
      };
      utterance.onend = done;
      utterance.onerror = done;
      pending.current += 1;
      setSpeaking(true);
      synth.speak(utterance);
      return true;
    },
    [synth, muted, voices],
  );

  const toggleMuted = useCallback((): void => {
    // Muting mid-sentence means silence now, not after the sentence.
    if (!muted) cancel();
    toggleStoreMuted();
  }, [muted, cancel, toggleStoreMuted]);

  return { supported, muted, toggleMuted, speaking, speak, cancel };
}

export type Spoken = { id: string; text: string };

/**
 * Reads aloud each message that appears while the page is open. What is already there on the
 * first render is history and stays silent; so is anything that arrives while muted.
 */
export function useSpeakArrivals(messages: readonly Spoken[]): Speech {
  const speech = useSpeech();
  const seen = useRef<Set<string> | null>(null);
  if (seen.current === null) seen.current = new Set(messages.map((message) => message.id));
  const { speak } = speech;

  useEffect(() => {
    const known = seen.current;
    if (!known) return;
    for (const message of messages) {
      if (known.has(message.id)) continue;
      known.add(message.id);
      speak(message.text);
    }
  }, [messages, speak]);

  return speech;
}
