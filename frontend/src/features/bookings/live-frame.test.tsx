import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LiveFrame } from "./live-frame";

/** A stand-in for `Image` whose loads the test completes by hand. */
class FakeImage {
  static created: FakeImage[] = [];
  onload: (() => void) | null = null;
  src = "";
  constructor() {
    FakeImage.created.push(this);
  }
}

function loaded(src: string): void {
  const image = FakeImage.created.find((candidate) => candidate.src === src);
  act(() => image?.onload?.());
}

describe("LiveFrame", () => {
  beforeEach(() => {
    FakeImage.created = [];
    vi.stubGlobal("Image", FakeImage);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the step placeholder, not an empty image, until a frame loads", () => {
    render(<LiveFrame src="/frame?t=1" alt="What the agent sees" placeholder="step 2 · search" />);
    expect(screen.getByRole("status")).toHaveTextContent("step 2 · search");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    loaded("/frame?t=1");
    expect(screen.getByRole("img", { name: "What the agent sees" })).toHaveAttribute(
      "src",
      "/frame?t=1",
    );
  });

  it("keeps the last good frame while the next one loads or fails", () => {
    const { rerender } = render(<LiveFrame src="/frame?t=1" alt="frame" placeholder="…" />);
    loaded("/frame?t=1");
    rerender(<LiveFrame src="/frame?t=2" alt="frame" placeholder="…" />);
    expect(screen.getByRole("img")).toHaveAttribute("src", "/frame?t=1");
    loaded("/frame?t=2");
    expect(screen.getByRole("img")).toHaveAttribute("src", "/frame?t=2");
  });
});
