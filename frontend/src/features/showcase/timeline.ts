import { useEffect, useState } from "react";

const TICK_MS = 100;

/** How many cues (ms offsets, ascending) have passed `elapsedMs` into a scene. */
export function cueIndex(cues: readonly number[], elapsedMs: number): number {
  let passed = 0;
  for (const cue of cues) {
    if (cue > elapsedMs) break;
    passed += 1;
  }
  return passed;
}

/** Milliseconds since mount, ticking while `playing`; stops counting at `endMs`. */
export function useSceneClock(endMs: number, playing = true): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setElapsed((ms) => Math.min(endMs, ms + TICK_MS));
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, [endMs, playing]);
  return elapsed;
}
