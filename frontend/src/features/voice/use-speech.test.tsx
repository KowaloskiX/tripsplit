import { fireEvent, render, screen } from "@testing-library/react";
import { type FakeSynthesis, installSynthesis, voice } from "@tests/speech-mocks";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SpeakerToggle } from "./speaker-toggle";
import { guessLang, pickVoice } from "./speech-api";
import { useVoiceStore } from "./store";
import { SPEECH_RATE, type Spoken, useSpeakArrivals } from "./use-speech";

function Room({ messages }: { messages: Spoken[] }): ReactNode {
  const speech = useSpeakArrivals(messages);
  return <SpeakerToggle speech={speech} />;
}

const spokenTexts = (synthesis: FakeSynthesis): string[] =>
  synthesis.speak.mock.calls.map(([utterance]) => utterance.text);

let synthesis: FakeSynthesis;

beforeEach(() => {
  window.localStorage.clear();
  useVoiceStore.setState({ muted: true, lang: "pl-PL", hydrated: false });
  synthesis = installSynthesis([
    voice("en-US", "Samantha"),
    voice("pl-PL", "Zosia (network)", false),
    voice("pl-PL", "Zosia"),
  ]);
});

afterEach(() => vi.unstubAllGlobals());

describe("useSpeakArrivals + SpeakerToggle", () => {
  it("stays silent while muted, and never reads the history", () => {
    const history = [{ id: "1", text: "Voting is open." }];
    const { rerender } = render(<Room messages={history} />);
    rerender(<Room messages={[...history, { id: "2", text: "Two votes in." }]} />);
    expect(synthesis.speak).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Read the agent's replies aloud" }));
    rerender(<Room messages={[...history, { id: "2", text: "Two votes in." }]} />);
    // Unmuting does not replay what arrived while muted.
    expect(synthesis.speak).not.toHaveBeenCalled();
  });

  it("reads new messages once unmuted, with a matching voice at 1.05×", () => {
    const history = [{ id: "1", text: "Voting is open." }];
    const { rerender } = render(<Room messages={history} />);
    fireEvent.click(screen.getByRole("button", { name: "Read the agent's replies aloud" }));

    rerender(
      <Room
        messages={[
          ...history,
          { id: "2", text: "Everyone paid, booking now." },
          { id: "3", text: "Pociąg EC 131 jest zarezerwowany." },
        ]}
      />,
    );
    expect(spokenTexts(synthesis)).toEqual([
      "Everyone paid, booking now.",
      "Pociąg EC 131 jest zarezerwowany.",
    ]);
    const [english, polish] = synthesis.speak.mock.calls.map(([utterance]) => utterance);
    expect(english?.lang).toBe("en-US");
    expect(english?.voice?.name).toBe("Samantha");
    expect(polish?.lang).toBe("pl-PL");
    expect(polish?.voice?.name).toBe("Zosia");
    expect(polish?.rate).toBe(SPEECH_RATE);
  });

  it("muting cuts the sentence short and is remembered", () => {
    render(<Room messages={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Read the agent's replies aloud" }));
    expect(JSON.parse(window.localStorage.getItem("tripsplit.voice") ?? "{}").muted).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Stop reading the agent's replies" }));
    expect(synthesis.cancel).toHaveBeenCalled();
    expect(JSON.parse(window.localStorage.getItem("tripsplit.voice") ?? "{}").muted).toBe(true);
  });

  it("restores an unmuted preference from storage", () => {
    window.localStorage.setItem("tripsplit.voice", JSON.stringify({ muted: false, lang: "pl-PL" }));
    const { rerender } = render(<Room messages={[]} />);
    expect(
      screen.getByRole("button", { name: "Stop reading the agent's replies" }),
    ).toBeInTheDocument();
    rerender(<Room messages={[{ id: "9", text: "Here are three ways to do it." }]} />);
    expect(spokenTexts(synthesis)).toEqual(["Here are three ways to do it."]);
  });

  it("renders nothing where the browser cannot speak", () => {
    vi.unstubAllGlobals();
    const { container } = render(<Room messages={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("voice picking", () => {
  const voices = [voice("en-GB", "Daniel"), voice("pl-PL", "Zosia"), voice("en-US", "Alex")];

  it("prefers the exact locale, then the same language", () => {
    expect(pickVoice(voices, "en-US")?.name).toBe("Alex");
    expect(pickVoice([voice("en-GB", "Daniel")], "en-US")?.name).toBe("Daniel");
    expect(pickVoice(voices, "de-DE")).toBeNull();
  });

  it("guesses Polish from letters and words, not from the currency", () => {
    expect(guessLang("Pociąg odjeżdża o 6:47")).toBe("pl-PL");
    expect(guessLang("Czy jest taniej?")).toBe("pl-PL");
    expect(guessLang("Three ways under 700 zł each")).toBe("en-US");
  });
});
