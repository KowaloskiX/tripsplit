import type { ReactNode } from "react";

import { useVoiceStore } from "./store";

/** PL / EN: which language the mic listens in. */
export function LangToggle({ disabled = false }: { disabled?: boolean }): ReactNode {
  const lang = useVoiceStore((state) => state.lang);
  const toggleLang = useVoiceStore((state) => state.toggleLang);
  const polish = lang === "pl-PL";
  return (
    <button
      type="button"
      onClick={toggleLang}
      disabled={disabled}
      aria-label={
        polish
          ? "Voice language: Polish. Switch to English"
          : "Voice language: English. Switch to Polish"
      }
      className="ticket-mono rounded-full px-2 py-1 text-[11px] uppercase text-muted transition duration-150 hover:bg-surface-sunken hover:text-ink disabled:opacity-50"
    >
      {polish ? "PL" : "EN"}
    </button>
  );
}
