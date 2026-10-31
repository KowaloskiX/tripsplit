/** Maps API shapes onto the quick-plan screen's props. */
import { packageImages, packageProvenance, segmentLine } from "@/features/proposals";
import type { ProposalResponse, QuickQuestionResponse, QuickTripRequest } from "@/lib/api";

import type { ClarifyingQuestion, QuickPackage } from "./model";

const MAX_LINKS = 4;

export function quickPackage(proposal: ProposalResponse): QuickPackage {
  const stay = proposal.items.find((item) => item.kind === "stay");
  return {
    id: proposal.id,
    title: proposal.title,
    stay: stay?.title ?? proposal.summary,
    images: packageImages(proposal),
    segments: proposal.items
      .filter((item) => item.kind === "transport")
      .flatMap((item) =>
        item.segments.map((segment) => ({
          mode: item.mode ?? "rail",
          label: segmentLine(segment),
        })),
      ),
    perPersonMinor: proposal.per_person_minor,
    provenance: packageProvenance(proposal),
    links: proposal.items.flatMap((item) => item.links ?? []).slice(0, MAX_LINKS),
  };
}

export function clarifyingQuestion(question: QuickQuestionResponse): ClarifyingQuestion {
  return {
    id: question.field,
    text: question.question,
    options: question.options.map((option) => option.label),
  };
}

export type QuickAnswers = Pick<QuickTripRequest, "destination" | "dates" | "group_size">;

/** A chip (its label -> value) or typed text, put into the field the question names. */
export function answerFor(question: QuickQuestionResponse, input: string): QuickAnswers | null {
  const value = question.options.find((option) => option.label === input)?.value ?? input.trim();
  if (!value) return null;
  if (question.field === "group_size") {
    const size = Number.parseInt(value, 10);
    return Number.isFinite(size) && size > 0 ? { group_size: size } : null;
  }
  return { [question.field]: value };
}
