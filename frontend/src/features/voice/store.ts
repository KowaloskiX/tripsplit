import { create } from "zustand";

import type { VoiceLang } from "./speech-api";

/**
 * Voice UI preferences: whether the agent reads its replies aloud, and which language the mic
 * listens in. Written to `localStorage` by hand (like the theme) — a mute that comes back on
 * refresh is not a mute.
 *
 * Muted by default: a page that starts talking unasked is a bad surprise, and browsers only
 * allow speech after a user gesture anyway — the unmute click is that gesture.
 */
export const VOICE_STORAGE_KEY = "tripsplit.voice";

type Stored = { muted: boolean; lang: VoiceLang };

const DEFAULTS: Stored = { muted: true, lang: "pl-PL" };

function load(): Stored {
  try {
    const raw = window.localStorage.getItem(VOICE_STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return DEFAULTS;
    const record = parsed as Record<string, unknown>;
    return {
      muted: typeof record.muted === "boolean" ? record.muted : DEFAULTS.muted,
      lang: record.lang === "en-US" || record.lang === "pl-PL" ? record.lang : DEFAULTS.lang,
    };
  } catch {
    return DEFAULTS;
  }
}

function save(state: Stored): void {
  // A private window can refuse to store; a preference is not worth breaking the page over.
  try {
    window.localStorage.setItem(VOICE_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignored on purpose
  }
}

type VoiceState = Stored & {
  hydrated: boolean;
  /** Reads the stored preferences once, after mount (the server renders the defaults). */
  hydrate: () => void;
  setMuted: (muted: boolean) => void;
  toggleMuted: () => void;
  setLang: (lang: VoiceLang) => void;
  toggleLang: () => void;
};

export const useVoiceStore = create<VoiceState>((set, get) => {
  const update = (patch: Partial<Stored>): void => {
    const next = { muted: get().muted, lang: get().lang, ...patch };
    save(next);
    set(next);
  };
  return {
    ...DEFAULTS,
    hydrated: false,
    hydrate: () => {
      if (get().hydrated) return;
      set({ ...load(), hydrated: true });
    },
    setMuted: (muted) => update({ muted }),
    toggleMuted: () => update({ muted: !get().muted }),
    setLang: (lang) => update({ lang }),
    toggleLang: () => update({ lang: get().lang === "pl-PL" ? "en-US" : "pl-PL" }),
  };
});
