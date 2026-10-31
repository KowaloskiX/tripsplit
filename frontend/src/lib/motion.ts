/**
 * Motion plumbing shared by every feature: the reduced-motion preference, eased interpolation
 * for counters, "did this just change" detection and the View Transitions wrapper.
 *
 * The rule the whole app follows: animate transform and opacity only, 150–600 ms, and when the
 * user asks for reduced motion, land on the final state at once.
 */
import { type RefObject, useEffect, useRef, useState, useSyncExternalStore } from "react";

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";

function subscribeReduced(onChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const query = window.matchMedia(REDUCED_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function readReduced(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.(REDUCED_QUERY).matches;
}

/** `true` when the user asked the OS for less motion. Server render assumes full motion. */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribeReduced, readReduced, () => false);
}

/** Decelerating curve: fast start, gentle landing — what a counter settling feels like. */
export function easeOutCubic(progress: number): number {
  const clamped = Math.min(1, Math.max(0, progress));
  return 1 - (1 - clamped) ** 3;
}

/** The value `progress` (0..1, eased) of the way from `from` to `to`, rounded to an integer. */
export function interpolate(from: number, to: number, progress: number): number {
  return Math.round(from + (to - from) * easeOutCubic(progress));
}

/**
 * Animates a number towards `target` over `durationMs` (requestAnimationFrame). The first
 * render shows `target` straight away unless a `from` is given (count up on mount); later
 * changes always animate from the shown value. Reduced motion never animates.
 */
export function useCountUp(
  target: number,
  { durationMs = 600, from }: { durationMs?: number; from?: number } = {},
): number {
  const reduced = usePrefersReducedMotion();
  const [shown, setShown] = useState(from !== undefined && !reduced ? from : target);
  const shownRef = useRef(shown);
  shownRef.current = shown;

  useEffect(() => {
    const from = shownRef.current;
    if (reduced || from === target || typeof requestAnimationFrame === "undefined") {
      setShown(target);
      return;
    }
    let frame = 0;
    const startedAt = performance.now();
    const step = (now: number): void => {
      const progress = (now - startedAt) / durationMs;
      setShown(interpolate(from, target, progress));
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, durationMs, reduced]);

  return shown;
}

/** The digits of a non-negative integer, padded on the left to `minDigits`. */
export function digitsOf(value: number, minDigits = 1): number[] {
  const whole = Math.max(0, Math.floor(Math.abs(value)));
  return whole
    .toString()
    .padStart(minDigits, "0")
    .split("")
    .map((digit) => Number(digit));
}

/**
 * `true` for `holdMs` after `value` changes from something else to `target` while the
 * component is mounted — the cue for a one-off celebration. Mounting already at `target` does
 * not count: reloading a booked trip should not replay the fireworks.
 */
export function useArrivedAt<T>(value: T, target: T, holdMs = 2400): boolean {
  const previous = useRef(value);
  const [arrived, setArrived] = useState(false);
  useEffect(() => {
    const before = previous.current;
    previous.current = value;
    if (value !== target) setArrived(false);
    else if (before !== value) setArrived(true);
  }, [value, target]);
  // A separate effect, so a re-run of the one above (StrictMode) cannot strand the flag.
  useEffect(() => {
    if (!arrived) return;
    const timer = window.setTimeout(() => setArrived(false), holdMs);
    return () => window.clearTimeout(timer);
  }, [arrived, holdMs]);
  return arrived;
}

/** Flips to `true` once the element scrolls into view, and stays there. */
export function useInView<E extends Element>(
  ref: RefObject<E | null>,
  rootMargin = "0px",
): boolean {
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (!element || seen) return;
    if (typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setSeen(true);
          observer.disconnect();
        }
      },
      { rootMargin, threshold: 0.15 },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, rootMargin, seen]);
  return seen;
}

/** `true` for the first `ms` after mount, then `false` — a short staged entrance. */
export function useForMs(ms: number, active = true): boolean {
  const [on, setOn] = useState(active);
  useEffect(() => {
    if (!active) return;
    setOn(true);
    const timer = window.setTimeout(() => setOn(false), ms);
    return () => window.clearTimeout(timer);
  }, [ms, active]);
  return on;
}

type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void) => unknown;
};

/** Runs `update` inside a View Transition where the browser has one, plainly otherwise. */
export function withViewTransition(update: () => void): void {
  const doc = typeof document === "undefined" ? undefined : (document as ViewTransitionDocument);
  if (!doc?.startViewTransition || readReduced()) {
    update();
    return;
  }
  doc.startViewTransition(update);
}
