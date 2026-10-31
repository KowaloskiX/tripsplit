import { ArrowRight } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { KindIcon } from "@/features/proposals";
import { isExample, LinkChips, PhotoStrip, ProvenancePill } from "@/features/trust";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import type { QuickPackage } from "./model";

type QuickPackageCardProps = {
  pkg: QuickPackage;
  currency: string;
  index: number;
  onTake?: ((id: string) => void) | undefined;
};

/** One package in the carousel: the hotel photo, how you get there, the price, "Take this". */
export function QuickPackageCard({
  pkg,
  currency,
  index,
  onTake,
}: QuickPackageCardProps): ReactNode {
  const example = isExample(pkg.provenance);
  return (
    <article
      aria-label={pkg.title}
      data-example={example}
      className={cn(
        "deal-in flex w-[84%] shrink-0 snap-center flex-col gap-3 rounded-[28px] bg-surface p-3 text-ink sm:w-[22.5rem]",
        // An example must never pass for a real offer: dashed, no shadow, muted.
        example ? "border-2 border-dashed border-ink/25" : "border border-line shadow-card",
      )}
      style={{ "--i": index } as CSSProperties}
    >
      <PhotoStrip images={pkg.images} layout="cover" example={example} />
      <div className="space-y-2 px-1.5">
        {pkg.provenance && <ProvenancePill provenance={pkg.provenance} />}
        <h3 className={cn("text-lg leading-snug tracking-[-0.02em]", example && "text-muted")}>
          {pkg.title}
        </h3>
        <p className="text-sm text-muted">{pkg.stay}</p>
        <ul className="space-y-1" aria-label="Getting there">
          {pkg.segments.map((segment) => (
            <li
              key={segment.label}
              className="flex items-center gap-2 text-xs tabular-nums text-muted"
            >
              <KindIcon
                kind="transport"
                mode={segment.mode}
                className="size-3.5 shrink-0 text-ink"
              />
              <span className="truncate">{segment.label}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="perforation mx-1.5" aria-hidden />
      <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-2 px-1.5 pb-1">
        <p
          className={cn(
            "ticket-mono whitespace-nowrap text-xl sm:text-2xl",
            example ? "text-muted" : "text-ink",
          )}
        >
          {formatMoney(pkg.perPersonMinor, currency)}
          <span className="font-sans text-sm text-muted"> / person</span>
        </p>
        {example ? (
          // Simulated suppliers (the demo fallback) can still be taken — labelled as such.
          <Button size="sm" variant="outline" onClick={() => onTake?.(pkg.id)}>
            Take this
          </Button>
        ) : (
          <Button size="sm" variant="lime" onClick={() => onTake?.(pkg.id)}>
            Take this
            <ArrowRight className="size-4" aria-hidden />
          </Button>
        )}
      </div>
      <LinkChips links={pkg.links} className="px-1.5 pb-1.5" />
    </article>
  );
}
