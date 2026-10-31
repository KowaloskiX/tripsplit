import { ExternalLink } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { ProposalResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import { KindIcon } from "./kind-icon";

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
        "flex flex-col rounded-[var(--radius-panel)] border bg-surface p-4",
        proposal.chosen
          ? "border-live ring-1 ring-live"
          : proposal.voted_by_me
            ? "border-accent"
            : "border-line",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold text-ink">{proposal.title}</h3>
        <div className="flex shrink-0 gap-1.5">
          {proposal.over_budget && (
            <span className="rounded-full border border-danger px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-danger">
              over budget
            </span>
          )}
          {proposal.chosen && (
            <span className="rounded-full bg-live px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-accent-ink">
              chosen
            </span>
          )}
        </div>
      </div>
      {proposal.summary && (
        <p className="mt-1 text-xs leading-relaxed text-muted">{proposal.summary}</p>
      )}

      <ul className="mt-3 space-y-2">
        {proposal.items.map((item) => (
          <li key={`${item.kind}-${item.title}`} className="flex items-start gap-2">
            <KindIcon kind={item.kind} />
            <div className="min-w-0 flex-1">
              <p className="text-xs text-ink">{item.title}</p>
              <a
                href={item.supplier_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 font-mono text-[10px] text-muted hover:text-accent"
              >
                {item.supplier}
                <ExternalLink className="size-3" aria-hidden />
              </a>
            </div>
            <span className="shrink-0 font-mono text-xs text-muted">
              {formatMoney(item.price_minor, currency)}
            </span>
          </li>
        ))}
      </ul>

      <div className="mt-4 flex items-end justify-between gap-3 border-t border-line pt-3">
        <div>
          <p className="font-mono text-lg tracking-tight text-ink">
            {formatMoney(proposal.per_person_minor, currency)}
            <span className="text-xs text-muted"> / person</span>
          </p>
          <p className="font-mono text-[11px] text-muted">
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
            {proposal.voted_by_me ? "Your vote" : "Vote"}
          </Button>
        )}
      </div>
    </article>
  );
}
