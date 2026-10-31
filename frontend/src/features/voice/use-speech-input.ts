import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import {
  type Recognition,
  type RecognitionErrorCode,
  type RecognitionResultEvent,
  recognitionConstructor,
  speechSynthesisOrNull,
  type VoiceLang,
} from "./speech-api";

export type SpeechInputStatus = "unsupported" | "idle" | "listening" | "denied" | "error";

export type SpeechInputOptions = {
  lang?: VoiceLang;
  /** Stop listening this long after the last thing heard. */
  silenceMs?: number;
  /** Give up this long after starting when nothing at all is heard. */
  noSpeechMs?: number;
  /** Every change of the live transcript (interim + final so far). */
  onInterim?: ((transcript: string) => void) | undefined;
  /** Once, when listening ends on its own or by `stop()`, with what was said. */
  onFinal?: ((transcript: string) => void) | undefined;
};

export type SpeechInput = {
  supported: boolean;
  status: SpeechInputStatus;
  listening: boolean;
  transcript: string;
  /** A sentence for a human, when the last attempt failed. */
  error: string | null;
  /** 0..1 — a loudness stand-in: spikes when words arrive, decays in silence. */
  level: number;
  start: () => void;
  /** Stop and submit what was heard. */
  stop: () => void;
  /** Stop and throw away what was heard. */
  cancel: () => void;
  toggle: () => void;
};

export const SILENCE_MS = 1600;
export const NO_SPEECH_MS = 8000;
const LEVEL_TICK_MS = 120;
const LEVEL_FLOOR = 0.18;

const ERROR_TEXT: Partial<Record<RecognitionErrorCode, string>> = {
  "not-allowed": "Microphone access is blocked — allow it in the address bar.",
  "service-not-allowed": "Microphone access is blocked — allow it in the address bar.",
  "no-speech": "I didn't hear anything — try again.",
  "audio-capture": "No microphone found.",
  network: "The speech service is unreachable — type instead.",
  "language-not-supported": "This browser can't recognise that language.",
};

const noSubscribe = (): (() => void) => () => {};

/** `true` once mounted in a browser that has SpeechRecognition; the server says `false`. */
export function useSpeechRecognitionSupported(): boolean {
  return useSyncExternalStore(
    noSubscribe,
    () => recognitionConstructor() !== null,
    () => false,
  );
}

/** Everything heard so far, final phrases first, then the one still being recognised. */
function transcriptOf(event: RecognitionResultEvent): string {
  const finals: string[] = [];
  const interims: string[] = [];
  for (let index = 0; index < event.results.length; index += 1) {
    const result = event.results[index];
    const alternative = result?.[0];
    if (!result || !alternative) continue;
    (result.isFinal ? finals : interims).push(alternative.transcript.trim());
  }
  return [...finals, ...interims].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
}

/**
 * Speech to text through the browser (Web Speech API): no keys, no backend. Interim results
 * stream through `onInterim`; listening stops after `silenceMs` without new words and hands
 * the whole utterance to `onFinal`.
 */
export function useSpeechInput({
  lang = "pl-PL",
  silenceMs = SILENCE_MS,
  noSpeechMs = NO_SPEECH_MS,
  onInterim,
  onFinal,
}: SpeechInputOptions = {}): SpeechInput {
  const supported = useSpeechRecognitionSupported();
  const [status, setStatus] = useState<Exclude<SpeechInputStatus, "unsupported">>("idle");
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [level, setLevel] = useState(0);

  const recognition = useRef<Recognition | null>(null);
  const heard = useRef("");
  const failed = useRef(false);
  const cancelled = useRef(false);
  const silence = useRef<number | undefined>(undefined);
  const callbacks = useRef({ onInterim, onFinal });
  callbacks.current = { onInterim, onFinal };

  const armSilence = useCallback((ms: number): void => {
    window.clearTimeout(silence.current);
    silence.current = window.setTimeout(() => recognition.current?.stop(), ms);
  }, []);

  const start = useCallback((): void => {
    const Constructor = recognitionConstructor();
    if (!Constructor || recognition.current) return;
    // The agent reading aloud would otherwise be transcribed as the user's words.
    speechSynthesisOrNull()?.cancel();

    const rec = new Constructor();
    rec.lang = lang;
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    heard.current = "";
    failed.current = false;
    cancelled.current = false;

    rec.onresult = (event) => {
      const text = transcriptOf(event);
      const grew = Math.max(0, text.length - heard.current.length);
      heard.current = text;
      setTranscript(text);
      setLevel(Math.min(1, 0.45 + grew / 18));
      callbacks.current.onInterim?.(text);
      armSilence(silenceMs);
    };
    rec.onerror = (event) => {
      if (event.error === "aborted") return;
      failed.current = true;
      const denied = event.error === "not-allowed" || event.error === "service-not-allowed";
      setStatus(denied ? "denied" : "error");
      setError(
        ERROR_TEXT[event.error as RecognitionErrorCode] ?? "Voice input failed — type instead.",
      );
    };
    rec.onend = () => {
      window.clearTimeout(silence.current);
      recognition.current = null;
      setLevel(0);
      const text = heard.current.trim();
      if (!failed.current) setStatus("idle");
      if (!failed.current && !cancelled.current && text) callbacks.current.onFinal?.(text);
    };

    recognition.current = rec;
    setTranscript("");
    setError(null);
    setStatus("listening");
    setLevel(LEVEL_FLOOR);
    try {
      rec.start();
    } catch {
      // Starting twice, or a browser that refuses outside a gesture.
      recognition.current = null;
      setStatus("error");
      setError("Voice input could not start — try again.");
      return;
    }
    armSilence(noSpeechMs);
  }, [lang, silenceMs, noSpeechMs, armSilence]);

  const stop = useCallback((): void => {
    window.clearTimeout(silence.current);
    recognition.current?.stop();
  }, []);

  const cancel = useCallback((): void => {
    window.clearTimeout(silence.current);
    cancelled.current = true;
    recognition.current?.abort();
  }, []);

  const listening = status === "listening";
  const toggle = useCallback((): void => (listening ? stop() : start()), [listening, start, stop]);

  // Words arriving push the level up; silence lets it sink back to a gentle idle.
  useEffect(() => {
    if (!listening) return;
    const timer = window.setInterval(
      () => setLevel((value) => Math.max(LEVEL_FLOOR, value * 0.82)),
      LEVEL_TICK_MS,
    );
    return () => window.clearInterval(timer);
  }, [listening]);

  useEffect(
    () => () => {
      window.clearTimeout(silence.current);
      cancelled.current = true;
      recognition.current?.abort();
      recognition.current = null;
    },
    [],
  );

  return {
    supported,
    status: supported ? status : "unsupported",
    listening,
    transcript,
    error,
    level,
    start,
    stop,
    cancel,
    toggle,
  };
}
