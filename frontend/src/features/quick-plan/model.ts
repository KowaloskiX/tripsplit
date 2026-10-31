/** The chat-first "Plan a trip" screen's data — props-driven; the lead wires POST /trips/quick. */
import type { Provenance, TrustImage, TrustLink } from "@/features/trust";
import type { TransportMode } from "@/lib/api";

export type QuickSegment = {
  mode: TransportMode;
  /** "EC 131 Warszawa → Praha · Fri 06:47". */
  label: string;
};

export type QuickPackage = {
  id: string;
  title: string;
  /** The stay's name, under the photo. */
  stay: string;
  images: readonly TrustImage[];
  segments: readonly QuickSegment[];
  perPersonMinor: number;
  provenance: Provenance;
  links: readonly TrustLink[];
};

export type ClarifyingQuestion = {
  id: string;
  /** "How many people?" */
  text: string;
  options: readonly string[];
};

/** idle → thinking (agent typing) → answered (packages) → choosing (who pays). */
export type QuickPlanStage = "idle" | "thinking" | "answered" | "choosing";

export type PaymentChoice = "invite" | "pay_all";

export const EXAMPLE_PROMPTS = [
  "Prague, 4–6 Dec, 6 people, 700 zł each",
  "Barcelona in March for 4, by plane",
  "A cheap weekend in Kraków for 8",
] as const;
