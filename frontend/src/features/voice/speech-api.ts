/**
 * The slice of the Web Speech API we use, typed by hand: `lib.dom` ships speechSynthesis but
 * not SpeechRecognition (Chrome, Edge and Safari expose it as `webkitSpeechRecognition`).
 * Everything here is read lazily, so the server render never touches `window`.
 */

export type VoiceLang = "pl-PL" | "en-US";

export const VOICE_LANGS: readonly VoiceLang[] = ["pl-PL", "en-US"];

export type RecognitionAlternative = { transcript: string };

export type RecognitionResult = {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: RecognitionAlternative;
};

export type RecognitionResultEvent = {
  readonly resultIndex: number;
  readonly results: { readonly length: number; [index: number]: RecognitionResult };
};

/** The `error` codes of SpeechRecognitionErrorEvent. */
export type RecognitionErrorCode =
  | "aborted"
  | "audio-capture"
  | "bad-grammar"
  | "language-not-supported"
  | "network"
  | "no-speech"
  | "not-allowed"
  | "service-not-allowed";

export type RecognitionErrorEvent = { readonly error: RecognitionErrorCode | string };

export type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: RecognitionResultEvent) => void) | null;
  onerror: ((event: RecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

export type RecognitionConstructor = new () => Recognition;

type SpeechWindow = Window & {
  SpeechRecognition?: RecognitionConstructor;
  webkitSpeechRecognition?: RecognitionConstructor;
};

/** The browser's recognizer class, or `null` (Firefox, server render). */
export function recognitionConstructor(): RecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const speechWindow = window as SpeechWindow;
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null;
}

/** The browser's speech synthesis, or `null`. */
export function speechSynthesisOrNull(): SpeechSynthesis | null {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
  return window.speechSynthesis ?? null;
}

/**
 * The best voice for `lang`: an exact locale match first (a local one over a network one, the
 * browser's default over the rest), then anything in the same language, else `null` (the
 * browser then picks from `utterance.lang`).
 */
export function pickVoice(
  voices: readonly SpeechSynthesisVoice[],
  lang: string,
): SpeechSynthesisVoice | null {
  const wanted = lang.toLowerCase().replace("_", "-");
  const base = wanted.split("-")[0] ?? wanted;
  const normal = (voice: SpeechSynthesisVoice): string =>
    voice.lang.toLowerCase().replace("_", "-");
  const score = (voice: SpeechSynthesisVoice): number =>
    (voice.localService ? 2 : 0) + (voice.default ? 1 : 0);
  const best = (pool: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null =>
    pool.sort((a, b) => score(b) - score(a))[0] ?? null;
  return (
    best(voices.filter((voice) => normal(voice) === wanted)) ??
    best(voices.filter((voice) => normal(voice).split("-")[0] === base))
  );
}

const POLISH_LETTERS = /[ąćęłńóśźż]/i;
const POLISH_WORDS = /\b(dla|osoby|jest|nie|jak|czy|tak|albo|grudnia|lub|oraz)\b/i;
/** "700 zł each" is still English — the currency alone says nothing about the language. */
const CURRENCY_SIGN = /zł/gi;

/** A cheap guess at the language of an agent message — the reader should not read Polish in English. */
export function guessLang(text: string): VoiceLang {
  const words = text.replace(CURRENCY_SIGN, "");
  return POLISH_LETTERS.test(words) || POLISH_WORDS.test(words) ? "pl-PL" : "en-US";
}
