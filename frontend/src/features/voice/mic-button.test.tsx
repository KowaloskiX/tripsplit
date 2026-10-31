import { act, fireEvent, render, screen } from "@testing-library/react";
import { FakeRecognition, installRecognition, uninstallRecognition } from "@tests/speech-mocks";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QuickPlan } from "@/features/quick-plan";

import { MicButton, UNSUPPORTED_HINT } from "./mic-button";
import { useVoiceStore } from "./store";
import { SILENCE_MS } from "./use-speech-input";

beforeEach(() => {
  window.localStorage.clear();
  useVoiceStore.setState({ muted: true, lang: "pl-PL", hydrated: false });
  installRecognition();
});

afterEach(() => {
  uninstallRecognition();
  vi.useRealTimers();
});

describe("MicButton", () => {
  it("is a quiet icon with a tooltip when the browser cannot listen", () => {
    uninstallRecognition();
    render(<MicButton />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: UNSUPPORTED_HINT })).toHaveAttribute(
      "title",
      UNSUPPORTED_HINT,
    );
  });

  it("starts listening in Polish with interim results, and stops on a second tap", () => {
    render(<MicButton />);
    fireEvent.click(screen.getByRole("button", { name: "Speak (Polish)" }));

    const recognition = FakeRecognition.last;
    expect(recognition.start).toHaveBeenCalledOnce();
    expect(recognition.lang).toBe("pl-PL");
    expect(recognition.interimResults).toBe(true);
    const stopButton = screen.getByRole("button", { name: "Stop listening" });
    expect(stopButton).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByTestId("mic-bar")).toHaveLength(4);

    fireEvent.click(stopButton);
    expect(recognition.stop).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Speak (Polish)" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("listens in English after the language toggle", () => {
    render(<MicButton withLang />);
    fireEvent.click(screen.getByRole("button", { name: /Switch to English/ }));
    fireEvent.click(screen.getByRole("button", { name: "Speak (English)" }));
    expect(FakeRecognition.last.lang).toBe("en-US");
    expect(JSON.parse(window.localStorage.getItem("tripsplit.voice") ?? "{}").lang).toBe("en-US");
  });

  it("explains a blocked microphone inline", () => {
    render(<MicButton />);
    fireEvent.click(screen.getByRole("button", { name: "Speak (Polish)" }));
    act(() => FakeRecognition.last.fail("not-allowed"));
    expect(screen.getByRole("alert")).toHaveTextContent("Microphone access is blocked");
  });

  it("throws the utterance away on Escape", () => {
    const onFinal = vi.fn();
    render(<MicButton onFinal={onFinal} />);
    fireEvent.click(screen.getByRole("button", { name: "Speak (Polish)" }));
    act(() => FakeRecognition.last.hear(["Praga", false]));
    fireEvent.keyDown(screen.getByRole("button", { name: "Stop listening" }), { key: "Escape" });
    expect(FakeRecognition.last.abort).toHaveBeenCalledOnce();
    expect(onFinal).not.toHaveBeenCalled();
  });
});

describe("MicButton in QuickPlan", () => {
  it("fills the input live and submits the final transcript after a silence", () => {
    vi.useFakeTimers();
    const onSubmit = vi.fn();
    render(<QuickPlan stage="idle" prompt={null} packages={[]} onSubmit={onSubmit} />);
    const input = screen.getByRole("textbox", { name: "Where, when, how many, budget?" });

    fireEvent.click(screen.getByRole("button", { name: "Speak (Polish)" }));
    const recognition = FakeRecognition.last;

    act(() => recognition.hear(["Praga", false]));
    expect(input).toHaveValue("Praga");

    act(() => recognition.hear(["Praga na weekend,", true], ["sześć osób", false]));
    expect(input).toHaveValue("Praga na weekend, sześć osób");

    act(() => recognition.hear(["Praga na weekend,", true], ["sześć osób", true]));
    expect(onSubmit).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(SILENCE_MS));
    expect(recognition.stop).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith("Praga na weekend, sześć osób");
    expect(input).toHaveValue("");
  });
});
