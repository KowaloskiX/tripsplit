import { Check, ExternalLink, Ticket } from "lucide-react";
import { type ReactNode, useState } from "react";

import { AvatarStack } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { DigitRoll } from "@/components/ui/number-roll";
import { type Provenance, ProvenancePill } from "@/features/trust";
import type { AttractionResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import { ATTRACTION_FILL, AttractionKindIcon, attractionKindLabel } from "./attraction-kind";

type AttractionCardProps = {
  attraction: AttractionResponse;
  /** Votes that put an attraction into the plan first (half the group). */
  majority: number;
  /** `undefined` = read-only (voting is over). */
  onToggle?: (() => void) | undefined;
  pending?: boolean;
};

/** Where an idea comes from, as the trust pill speaks it. */
export function attractionProvenance(source: string): Provenance | undefined {
  const text = source.trim();
  if (!text) return undefined;
  if (text === "live") return { kind: "live", source: "Wikipedia" };
  if (/demo|simulated/i.test(text)) return { kind: "test", source: text };
  return { kind: "live", source: text };
}

export function priceLabel(attraction: AttractionResponse): string {
  return attraction.price_per_person_minor === null
    ? "Free / pay on site"
    : `${formatMoney(attraction.price_per_person_minor, attraction.currency)} / person`;
}

export function AttractionCard({
  attraction,
  majority,
  onToggle,
  pending = false,
}: AttractionCardProps): ReactNode {
  const [broken, setBroken] = useState(false);
  const photo = attraction.image_url && !broken ? attraction.image_url : null;
  const provenance = attractionProvenance(attraction.provenance);
  const wanted = attraction.votes >= majority && majority > 0;
  return (
    <article
      className={cn(
        "flex min-w-0 flex-col overflow-hidden rounded-[var(--radius-panel)] border bg-surface transition duration-150",
        attraction.voted_by_me ? "border-ink shadow-card" : "border-line hover:shadow-card",
      )}
    >
      <div className={cn("relative h-28 shrink-0", ATTRACTION_FILL[attraction.kind])}>
        {photo ? (
          <img
            src={photo}
            alt=""
            loading="lazy"
            className="size-full object-cover"
            onError={() => setBroken(true)}
          />
        ) : (
          <span className="absolute inset-0 flex items-center justify-center text-pastel-ink/60">
            <AttractionKindIcon kind={attraction.kind} className="size-10" />
          </span>
        )}
        <span className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-surface/90 px-2.5 py-0.5 text-xs font-medium text-ink backdrop-blur">
          <AttractionKindIcon kind={attraction.kind} className="size-3.5" />
          {attractionKindLabel(attraction.kind)}
        </span>
        {wanted && (
          <span className="pop absolute right-3 top-3 rounded-full bg-sun px-2.5 py-0.5 text-xs font-medium text-sun-ink">
            in the plan
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <h3 className="text-base font-medium leading-snug tracking-[-0.01em] text-ink">
          {attraction.title}
        </h3>
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          <span className="ticket-mono text-ink">{priceLabel(attraction)}</span>
          {attraction.bookable && (
            <span className="inline-flex items-center gap-1">
              <Ticket className="size-3.5" aria-hidden />
              agent buys tickets
            </span>
          )}
          {attraction.opens && attraction.closes && (
            <span>
              {attraction.opens}–{attraction.closes}
            </span>
          )}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {provenance && <ProvenancePill provenance={provenance} />}
          {attraction.website && (
            <a
              href={attraction.website}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-muted underline-offset-2 hover:text-ink hover:underline"
            >
              Website
              <ExternalLink className="size-3" aria-hidden />
            </a>
          )}
        </div>
        <div className="mt-auto flex items-center justify-between gap-2 pt-2">
          <span className="flex min-w-0 items-center gap-2 text-xs text-muted">
            {attraction.voters.length > 0 && (
              <AvatarStack
                people={attraction.voters.map((v) => ({ id: v.user_id, name: v.display_name }))}
                max={4}
              />
            )}
            <span className="ticket-mono">
              <DigitRoll value={attraction.votes} /> {attraction.votes === 1 ? "vote" : "votes"}
            </span>
          </span>
          {onToggle && (
            <Button
              size="sm"
              variant={attraction.voted_by_me ? "solid" : "outline"}
              onClick={onToggle}
              disabled={pending}
              aria-pressed={attraction.voted_by_me}
            >
              {attraction.voted_by_me && <Check className="size-4" aria-hidden />}
              {attraction.voted_by_me ? "Want it" : "I want this"}
            </Button>
          )}
        </div>
      </div>
    </article>
  );
}
