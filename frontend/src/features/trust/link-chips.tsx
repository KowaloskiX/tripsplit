import { Activity, ExternalLink, MapPin, SearchCheck, Ticket } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import type { TrustLink, TrustLinkKind } from "./model";

const ICON: Record<TrustLinkKind, typeof Ticket> = {
  book: Ticket,
  verify: SearchCheck,
  map: MapPin,
  status: Activity,
};

type LinkChipsProps = {
  links: readonly TrustLink[];
  /** On a dark surface (the agent's bubble, mission control). */
  inverted?: boolean;
  className?: string;
};

/** "Open on intercity.pl ↗", "Check on Google Flights ↗" — every claim one click from proof. */
export function LinkChips({ links, inverted = false, className }: LinkChipsProps): ReactNode {
  if (links.length === 0) return null;
  return (
    <ul className={cn("flex flex-wrap gap-1.5", className)} aria-label="Check it yourself">
      {links.map((link) => {
        const Icon = ICON[link.kind];
        return (
          <li key={`${link.kind}-${link.url}`}>
            <a
              href={link.url}
              target="_blank"
              rel="noreferrer"
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition duration-150 active:scale-[0.97]",
                inverted
                  ? "border-white/15 text-agent-fg/80 hover:border-lime/60 hover:text-agent-fg"
                  : "border-line text-muted hover:border-ink/30 hover:text-ink",
              )}
            >
              <Icon className="size-3.5" aria-hidden />
              {link.label}
              <ExternalLink className="size-3 opacity-60" aria-hidden />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          </li>
        );
      })}
    </ul>
  );
}
