/**
 * Test doubles for the Web Speech API (jsdom has neither half) — for any test that mounts a
 * mic (`features/voice` MicButton) or a speaker.
 */
import { vi } from "vitest";

type ResultEvent = {
  resultIndex: number;
  results: { isFinal: boolean; length: number; 0: { transcript: string } }[];
};

export class FakeRecognition {
  static instances: FakeRecognition[] = [];
  lang = "";
  continuous = false;
  interimResults = false;
  maxAlternatives = 1;
  onresult: ((event: ResultEvent) => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  onstart: (() => void) | null = null;
  started = false;
  start = vi.fn(() => {
    this.started = true;
    this.onstart?.();
  });
  stop = vi.fn(() => this.end());
  abort = vi.fn(() => {
    this.onerror?.({ error: "aborted" });
    this.end();
  });

  constructor() {
    FakeRecognition.instances.push(this);
  }

  static get last(): FakeRecognition {
    const last = FakeRecognition.instances.at(-1);
    if (!last) throw new Error("No recognition was created");
    return last;
  }

  /** Every phrase heard so far, as `[transcript, isFinal]`. */
  hear(...phrases: [string, boolean][]): void {
    const results = phrases.map(([transcript, isFinal]) => ({
      isFinal,
      length: 1,
      0: { transcript },
    }));
    this.onresult?.({ resultIndex: 0, results });
  }

  fail(error: string): void {
    this.onerror?.({ error });
    this.end();
  }

  private end(): void {
    if (!this.started) return;
    this.started = false;
    this.onend?.();
  }
}

type SpeechWindow = { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown };

export function installRecognition(): void {
  FakeRecognition.instances = [];
  (window as unknown as SpeechWindow).webkitSpeechRecognition = FakeRecognition;
}

export function uninstallRecognition(): void {
  const speechWindow = window as unknown as SpeechWindow;
  delete speechWindow.SpeechRecognition;
  delete speechWindow.webkitSpeechRecognition;
}

export class FakeUtterance {
  lang = "";
  rate = 1;
  voice: SpeechSynthesisVoice | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly text: string) {}
}

export type FakeSynthesis = {
  speak: ReturnType<typeof vi.fn<(utterance: FakeUtterance) => void>>;
  cancel: ReturnType<typeof vi.fn<() => void>>;
  getVoices: () => SpeechSynthesisVoice[];
  addEventListener: () => void;
  removeEventListener: () => void;
};

export function voice(lang: string, name: string, localService = true): SpeechSynthesisVoice {
  return { lang, name, localService, default: false, voiceURI: name } as SpeechSynthesisVoice;
}

export function installSynthesis(voices: SpeechSynthesisVoice[] = []): FakeSynthesis {
  const synthesis: FakeSynthesis = {
    speak: vi.fn(),
    cancel: vi.fn(),
    getVoices: () => voices,
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  vi.stubGlobal("speechSynthesis", synthesis);
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  return synthesis;
}
