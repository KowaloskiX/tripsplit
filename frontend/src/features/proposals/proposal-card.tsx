import { Check, ExternalLink } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ProposalResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import { KIND_FILL, KindIcon } from "./kind-icon";

type ProposalCardProps = {
  proposal: ProposalResponse;
  currency: string;
  /** `undefined` hides the vote button (voting is over or not open). */
  onVote?: (() => void) | undefined;
  voting?: boolean;
};

export function ProposalCard({ proposal, currency, onVote, voting }: ProposalCardProps): ReactNode {
  return (
    <article
      className={cn(
        "flex min-w-0 flex-col overflow-hidden rounded-[var(--radius-panel)] border bg-surface transition duration-150",
        proposal.chosen || proposal.voted_by_me
          ? "border-ink shadow-card"
          : "border-line hover:border-ink/30 hover:shadow-card",
      )}
    >
      <div className="flex items-start justify-between gap-3 px-5 pt-6 sm:px-6">
        <h3 className="text-xl leading-snug tracking-[-0.02em] text-ink">{proposal.title}</h3>
        <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
          {proposal.over_budget && <Badge tone="danger">over budget</Badge>}
          {proposal.chosen && (
            <Badge tone="lime">
              <Check className="size-3" strokeWidth={3} aria-hidden />
              chosen
            </Badge>
          )}
        </div>
      </div>
      {proposal.summary && (
        <p className="mt-2 px-5 text-[15px] leading-relaxed text-muted sm:px-6">
          {proposal.summary}
        </p>
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
              <KindIcon kind={item.kind} />
            </span>
            <div className="min-w-[9rem] flex-1">
              <p className="text-sm font-medium leading-snug text-ink">{item.title}</p>
              <a
                href={item.supplier_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs text-muted underline-offset-2 transition duration-150 hover:text-ink hover:underline"
              >
                {item.supplier}
                <ExternalLink className="size-3" aria-hidden />
              </a>
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
            {formatMoney(proposal.total_minor, currency)} total · {proposal.votes}{" "}
            {proposal.votes === 1 ? "vote" : "votes"}
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
    </article>
  );
}
