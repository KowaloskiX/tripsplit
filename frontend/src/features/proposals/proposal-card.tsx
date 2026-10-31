import { Check, ExternalLink } from "lucide-react";
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
  /** Most votes so far, while voting is open: the card glows lime. */
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
  const stay = proposal.items.find((item) => item.kind === "stay" && item.images.length > 0);
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
          <Stamp tone="lime" rotate={-8} delayMs={120}>
            <Check className="size-3.5" strokeWidth={3} aria-hidden />
            chosen
          </Stamp>
        </span>
      )}
      {/* Clips the perforation notches; the stamp and the glow sit outside it. */}
      <div className="flex min-w-0 flex-col overflow-hidden rounded-[inherit]">
        {images.length > 0 && (
          <PhotoStrip
            images={images}
            layout="cover"
            example={example}
            className="mx-3 mt-3 sm:mx-4 sm:mt-4"
          />
        )}
        <div className="flex items-start justify-between gap-3 px-5 pt-6 sm:px-6">
          <h3 className="text-xl leading-snug tracking-[-0.02em] text-ink">{proposal.title}</h3>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            {proposal.over_budget && <Badge tone="danger">over budget</Badge>}
          </div>
        </div>
        {proposal.summary && (
          <p className="mt-2 px-5 text-[15px] leading-relaxed text-muted sm:px-6">
            {proposal.summary}
          </p>
        )}
        {provenance && (
          <div className="mt-2.5 px-5 sm:px-6">
            <ProvenancePill provenance={provenance} />
          </div>
        )}

        <ul className="mt-5 space-y-2 px-3 sm:px-6">
          {proposal.items.map((item) => (
            <li
              key={`${item.kind}-${item.title}`}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[20px] bg-surface-sunken px-3 py-2.5"
            >
              <span
                className={cn(
                  "inline-flex size-10 shrink-0 items-center justify-center rounded-2xl text-pastel-ink",
                  KIND_FILL[item.kind],
                )}
              >
                <KindIcon kind={item.kind} mode={item.mode} className="size-[18px] shrink-0" />
              </span>
              <div className="min-w-[9rem] flex-1">
                <p className="text-sm font-medium leading-snug text-ink">{item.title}</p>
                {item.segments.length > 0 && (
                  <ul className="mt-0.5 space-y-0.5" aria-label="Segments">
                    {item.segments.map((segment) => (
                      <li
                        key={`${segment.number}-${segment.departs_at}`}
                        className="ticket-mono text-[11px] text-muted"
                      >
                        {segmentLine(segment)}
                      </li>
                    ))}
                  </ul>
                )}
                <a
                  href={item.supplier_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-muted underline-offset-2 transition duration-150 hover:text-ink hover:underline"
                >
                  {item.supplier}
                  <ExternalLink className="size-3" aria-hidden />
                </a>
                {(item.links ?? []).length > 0 && (
                  <LinkChips links={item.links} className="mt-1.5" />
                )}
              </div>
              <span className="ticket-mono ml-auto shrink-0 text-sm text-ink">
                {formatMoney(item.price_minor, currency)}
              </span>
            </li>
          ))}
        </ul>

        {/* The stub: a torn-off strip with what each person pays. */}
        <div aria-hidden className="relative mt-6">
          <span className="absolute -left-3 top-1/2 size-6 -translate-y-1/2 rounded-full border border-line bg-surface" />
          <span className="absolute -right-3 top-1/2 size-6 -translate-y-1/2 rounded-full border border-line bg-surface" />
          <div className="perforation mx-6" />
        </div>
        <div className="flex items-end justify-between gap-3 px-6 pt-4 pb-6">
          <div>
            <p className="ticket-mono text-2xl text-ink">
              {formatMoney(proposal.per_person_minor, currency)}
              <span className="font-sans text-sm text-muted"> / person</span>
            </p>
            <p className="ticket-mono mt-1 text-xs text-muted">
              {formatMoney(proposal.total_minor, currency)} total ·{" "}
              <DigitRoll value={proposal.votes} /> {proposal.votes === 1 ? "vote" : "votes"}
            </p>
          </div>
          {onVote && (
            <Button
              size="sm"
              variant={proposal.voted_by_me ? "solid" : "outline"}
              onClick={onVote}
              disabled={voting || proposal.voted_by_me}
            >
              {proposal.voted_by_me && <Check className="size-4" aria-hidden />}
              {proposal.voted_by_me ? "Your vote" : "Vote"}
            </Button>
          )}
        </div>
        {links.length > 0 && <LinkChips links={links} className="-mt-2 px-6 pb-6" />}
      </div>
    </article>
  );
}
