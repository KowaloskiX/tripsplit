import { Check } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DigitRoll } from "@/components/ui/number-roll";
import { Stamp } from "@/components/ui/stamp";
import {
  imagesFromApi,
  isExample,
  LinkChips,
  PhotoStrip,
  type Provenance,
  ProvenancePill,
  provenanceFromApi,
  type TrustImage,
  type TrustLink,
} from "@/features/trust";
import type { ProposalResponse, SegmentResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import { KIND_FILL, KindIcon } from "./kind-icon";

type ProposalCardProps = {
  proposal: ProposalResponse;
  currency: string;
  /** `undefined` hides the vote button (voting is over or not open). */
  onVote?: (() => void) | undefined;
  voting?: boolean;
  /** Most votes so far, while voting is open: the card glows. */
  leading?: boolean;
  /** Lost the vote and is on its way out: steps back and fades. */
  receding?: boolean;
  /** Where the prices come from — shown as a pill; an example is styled as one. */
  provenance?: Provenance | undefined;
  /** "Open on intercity.pl", "Hotel on map"… */
  links?: readonly TrustLink[] | undefined;
  /** Hotel photos, shown as a strip at the top. */
  images?: readonly TrustImage[] | undefined;
};

const TIME = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
});

/** "LO 401 WAW → BCN · Fri 07:05" — one line per leg, whatever the mode. */
export function segmentLine(segment: SegmentResponse): string {
  return `${segment.number} ${segment.origin} → ${segment.destination} · ${TIME.format(
    new Date(segment.departs_at),
  )}`;
}

/** "Budget: PKP Intercity train + Mama Shelter…" -> "Budget": the items below say the rest. */
export function packageHeading(title: string): string {
  const tier = title.split(":", 1)[0]?.trim();
  return tier && tier.length < title.length ? tier : title;
}

/** A transport item reads as its carrier (the legs say where and when); anything else by name. */
function itemName(item: ProposalResponse["items"][number]): string {
  return item.kind === "transport" && item.segments.length > 0 ? item.supplier : item.title;
}

const CAUTION: Record<Provenance["kind"], number> = { live: 0, test: 1, sandbox: 1, example: 2 };

/** The package's pill: its least trustworthy transport/stay item (activities are extras, so a
 *  simulated museum ticket does not mark a live train + hotel as an example). */
export function packageProvenance(proposal: ProposalResponse): Provenance | undefined {
  let worst: Provenance | undefined;
  for (const item of proposal.items) {
    if (item.kind === "activity") continue;
    const provenance = provenanceFromApi(item.provenance);
    if (provenance && (!worst || CAUTION[provenance.kind] > CAUTION[worst.kind]))
      worst = provenance;
  }
  return worst;
}

/** The stay's photos make the card's cover. */
export function packageImages(proposal: ProposalResponse): TrustImage[] {
  const stay = proposal.items.find(
    (item) => item.kind === "stay" && (item.images ?? []).length > 0,
  );
  return stay ? imagesFromApi(stay.images, stay.title) : [];
}

export function ProposalCard({
  proposal,
  currency,
  onVote,
  voting,
  leading = false,
  receding = false,
  provenance: provenanceProp,
  links = [],
  images: imagesProp,
}: ProposalCardProps): ReactNode {
  const provenance = provenanceProp ?? packageProvenance(proposal);
  const images = imagesProp ?? packageImages(proposal);
  const example = isExample(provenance);
  return (
    <article
      data-leading={leading}
      className={cn(
        "lead-glow min-w-0 rounded-[var(--radius-panel)] border bg-surface transition duration-150",
        proposal.chosen || proposal.voted_by_me
          ? "border-ink shadow-card"
          : "border-line hover:border-ink/30 hover:shadow-card",
        // An example must never pass for a real offer.
        example && "border-2 border-dashed border-ink/25 shadow-none",
        proposal.chosen && "thump",
        receding && "recede",
      )}
    >
      {proposal.chosen && (
        <span className="absolute -top-3 right-5 z-10">
          <Stamp tone="sun" rotate={-8} delayMs={120}>
            <Check className="size-3.5" strokeWidth={3} aria-hidden />
            chosen
          </Stamp>
        </span>
      )}
      {/* A search-result row: photo left, what you get in the middle, the price and the action
          right. Clipped to the card's corners; the stamp and the glow sit outside it. */}
      <div className="flex min-w-0 flex-col overflow-hidden rounded-[inherit] sm:flex-row">
        {images.length > 0 && (
          <PhotoStrip
            images={images}
            layout="cover"
            example={example}
            className="shrink-0 rounded-none sm:w-52 sm:[&>span]:aspect-auto sm:[&>span]:h-full"
          />
        )}
        <div className="flex min-w-0 flex-1 flex-col p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3
                className="text-lg font-semibold tracking-[-0.01em] text-ink"
                title={proposal.title}
              >
                {packageHeading(proposal.title)}
              </h3>
              {provenance && <ProvenancePill provenance={provenance} className="mt-1" />}
            </div>
            {proposal.over_budget && <Badge tone="danger">over budget</Badge>}
          </div>

          <ul className="mt-3 space-y-2.5">
            {proposal.items.map((item) => (
              <li key={`${item.kind}-${item.title}`} className="flex items-start gap-2.5">
                <span
                  className={cn(
                    "mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-md text-pastel-ink",
                    KIND_FILL[item.kind],
                  )}
                >
                  <KindIcon kind={item.kind} mode={item.mode} className="size-4 shrink-0" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-ink" title={item.title}>
                    {itemName(item)}
                  </p>
                  {item.segments.length > 0 && (
                    <ul aria-label="Segments">
                      {item.segments.map((segment) => (
                        <li
                          key={`${segment.number}-${segment.departs_at}`}
                          className="truncate text-xs tabular-nums text-muted"
                        >
                          {segmentLine(segment)}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </li>
            ))}
          </ul>

          <div className="mt-auto flex items-end justify-between gap-3 pt-4">
            <p className="text-xs text-muted">
              <DigitRoll value={proposal.votes} /> {proposal.votes === 1 ? "vote" : "votes"}
            </p>
            <div className="flex items-center gap-3">
              <p className="text-right">
                <span className="ticket-mono block text-xl font-semibold text-ink">
                  {formatMoney(proposal.per_person_minor, currency)}
                </span>
                <span className="text-xs text-muted">per person</span>
              </p>
              {onVote && (
                <Button
                  variant={proposal.voted_by_me ? "outline" : "sun"}
                  onClick={onVote}
                  disabled={voting || proposal.voted_by_me}
                >
                  {proposal.voted_by_me && <Check className="size-4" aria-hidden />}
                  {proposal.voted_by_me ? "Your vote" : "Vote"}
                </Button>
              )}
            </div>
          </div>
          {links.length > 0 && <LinkChips links={links} className="mt-3" />}
        </div>
      </div>
    </article>
  );
}
