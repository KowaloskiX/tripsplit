import { Volume2, VolumeX } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import type { Speech } from "./use-speech";

type SpeakerToggleProps = {
  /** The `useSpeech()` / `useSpeakArrivals()` result of the screen that speaks. */
  speech: Pick<Speech, "supported" | "muted" | "toggleMuted" | "speaking">;
  className?: string;
};

/** Mute / unmute the agent reading its replies aloud. Absent where the browser cannot speak. */
export function SpeakerToggle({ speech, className }: SpeakerToggleProps): ReactNode {
  if (!speech.supported) return null;
  const { muted, speaking } = speech;
  return (
    <button
      type="button"
      onClick={speech.toggleMuted}
      aria-pressed={!muted}
      aria-label={muted ? "Read the agent's replies aloud" : "Stop reading the agent's replies"}
      title={muted ? "Read replies aloud" : "Mute the agent"}
      className={cn(
        "inline-flex size-8 items-center justify-center rounded-full transition duration-150 active:scale-[0.95] motion-reduce:active:scale-100",
        muted ? "text-muted hover:bg-surface-sunken hover:text-ink" : "bg-lime/20 text-ink",
        className,
      )}
    >
      {muted ? (
        <VolumeX className="size-4" aria-hidden />
      ) : (
        <Volume2
          className={cn("size-4", speaking && "animate-pulse motion-reduce:animate-none")}
          aria-hidden
        />
      )}
    </button>
  );
}
