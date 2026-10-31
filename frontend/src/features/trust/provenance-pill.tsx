import { FlaskConical, Radio, ShieldQuestion, TestTube } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { type Provenance, type ProvenanceKind, provenanceLabel } from "./model";

const STYLE: Record<ProvenanceKind, string> = {
  live: "bg-lime text-pastel-ink",
  test: "bg-info-soft text-info",
  sandbox: "bg-warn-soft text-warn",
  // Deliberately the weakest look: dashed, no fill — it must never pass for a real offer.
  example: "border border-dashed border-ink/30 text-muted",
};

const ICON: Record<ProvenanceKind, typeof Radio> = {
  live: Radio,
  test: TestTube,
  sandbox: FlaskConical,
  example: ShieldQuestion,
};

type ProvenancePillProps = {
  provenance: Provenance;
  /** For tests and screenshots; defaults to the current time. */
  now?: number;
  className?: string;
};

/** "Live from PKP Intercity · checked 2 min ago", "Duffel test data", "Example · not bookable". */
export function ProvenancePill({ provenance, now, className }: ProvenancePillProps): ReactNode {
  const Icon = ICON[provenance.kind];
  const label = provenanceLabel(provenance, now);
  return (
    <span
      data-provenance={provenance.kind}
      title={label}
      className={cn(
        "ticket-mono inline-flex max-w-full items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px]",
        STYLE[provenance.kind],
        className,
      )}
    >
      {provenance.kind === "live" ? (
        <span aria-hidden className="relative inline-flex size-1.5">
          <span className="absolute inset-0 animate-ping rounded-full bg-current opacity-60 motion-reduce:animate-none" />
          <span className="relative size-1.5 rounded-full bg-current" />
        </span>
      ) : (
        <Icon className="size-3 shrink-0" aria-hidden />
      )}
      <span className="truncate">{label}</span>
    </span>
  );
}
