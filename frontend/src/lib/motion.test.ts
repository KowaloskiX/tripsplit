import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  digitsOf,
  easeOutCubic,
  interpolate,
  useArrivedAt,
  useCountUp,
  usePrefersReducedMotion,
} from "./motion";

function mockReducedMotion(reduced: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: reduced && query.includes("reduce"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("easing and interpolation", () => {
  it("clamps the curve to 0..1", () => {
    expect(easeOutCubic(-1)).toBe(0);
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(1)).toBe(1);
    expect(easeOutCubic(2)).toBe(1);
  });

  it("decelerates: past the halfway value at half time", () => {
    expect(easeOutCubic(0.5)).toBeGreaterThan(0.5);
  });

  it("interpolates whole numbers in both directions", () => {
    expect(interpolate(0, 100, 0)).toBe(0);
    expect(interpolate(0, 100, 1)).toBe(100);
    expect(interpolate(100, 40, 1)).toBe(40);
    expect(Number.isInteger(interpolate(3, 59_300, 0.37))).toBe(true);
  });
});

describe("digitsOf", () => {
  it("splits an integer into digits", () => {
    expect(digitsOf(593)).toEqual([5, 9, 3]);
  });

  it("pads on the left", () => {
    expect(digitsOf(6, 2)).toEqual([0, 6]);
  });

  it("drops fractions and the sign", () => {
    expect(digitsOf(-12.9)).toEqual([1, 2]);
  });
});

describe("usePrefersReducedMotion", () => {
  it("reads the media query", () => {
    mockReducedMotion(true);
    expect(renderHook(() => usePrefersReducedMotion()).result.current).toBe(true);
  });

  it("is false when the user did not ask", () => {
    mockReducedMotion(false);
    expect(renderHook(() => usePrefersReducedMotion()).result.current).toBe(false);
  });
});

describe("useCountUp", () => {
  it("lands on the new target at once with reduced motion", () => {
    mockReducedMotion(true);
    const { result, rerender } = renderHook(({ value }) => useCountUp(value), {
      initialProps: { value: 10 },
    });
    expect(result.current).toBe(10);
    rerender({ value: 90 });
    expect(result.current).toBe(90);
  });

  it("starts at the target, not at zero, by default", () => {
    mockReducedMotion(false);
    expect(renderHook(() => useCountUp(42)).result.current).toBe(42);
  });
});

describe("useArrivedAt", () => {
  it("fires on a change into the target, then clears", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ value }) => useArrivedAt(value, "done", 1000), {
      initialProps: { value: "paying" },
    });
    expect(result.current).toBe(false);
    rerender({ value: "done" });
    expect(result.current).toBe(true);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(false);
  });

  it("does not fire when mounted already at the target", () => {
    const { result } = renderHook(() => useArrivedAt("done", "done"));
    expect(result.current).toBe(false);
  });
});
