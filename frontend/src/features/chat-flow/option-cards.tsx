import { BedDouble, Bus, Check, MapPin, Plane, Ship, Star, TrainFront } from "lucide-react";
import { type CSSProperties, type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { LinkChips, ProvenancePill, provenanceFromApi } from "@/features/trust";
import type { OptionResponse, TransportMode } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import { changesLabel, optionImage, optionLegs, optionLinks } from "./from-api";

const MODE_ICON: Record<TransportMode, typeof TrainFront> = {
  rail: TrainFront,
  flight: Plane,
  bus: Bus,
  ferry: Ship,
};

function Provenance({ option }: { option: OptionResponse }): ReactNode {
  const provenance = provenanceFromApi(option.items[0]?.provenance);
  return provenance ? <ProvenancePill provenance={provenance} /> : null;
}

function PerPerson({
  option,
  currency,
  align = "right",
}: {
  option: OptionResponse;
  currency: string;
  align?: "left" | "right";
}): ReactNode {
  return (
    <span className={align === "right" ? "shrink-0 text-right" : "shrink-0 text-left"}>
      <span className="ticket-mono block text-base text-ink">
        {formatMoney(option.per_person_minor, currency)}
      </span>
      <span className="block text-[11px] text-muted">per person</span>
    </span>
  );
}

function verifyLinks(option: OptionResponse) {
  const links = optionLinks(option);
  const preferred = links.filter((link) => link.kind === "verify" || link.kind === "map");
  return (preferred.length > 0 ? preferred : links).slice(0, 2);
}

type PickProps = {
  option: OptionResponse;
  currency: string;
  index: number;
  picked: boolean;
  onPick: (optionId: string) => void;
};

/** One way to get there, on one line per journey: number, times, duration, changes. */
export function TransportCard({ option, currency, index, picked, onPick }: PickProps): ReactNode {
  const legs = optionLegs(option);
  const mode = option.items[0]?.mode ?? "rail";
  const Icon = MODE_ICON[mode];
  return (
    <li className="rise-in list-none" style={{ "--i": index, "--delay": "120ms" } as CSSProperties}>
      <article
        aria-label={option.label}
        className={cn(
          "rounded-[24px] border bg-surface p-4 shadow-card transition",
          picked ? "border-sun ring-2 ring-sun/30" : "border-line",
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <Icon className="size-4 shrink-0 text-muted" aria-hidden />
            <h3 className="truncate text-sm font-medium text-ink">{option.label}</h3>
          </div>
          <PerPerson option={option} currency={currency} />
        </div>
        <ul className="mt-2 space-y-1">
          {legs.map((leg) => (
            <li key={`${leg.numbers}-${leg.departs}`} className="ticket-mono text-xs text-muted">
              <span className="text-ink">{leg.numbers}</span> · {leg.departs} → {leg.arrives} ·{" "}
              {leg.duration} · {changesLabel(leg.changes)}
            </li>
          ))}
          {legs.length === 0 && (
            <li className="text-xs text-muted">{option.items[0]?.details ?? ""}</li>
          )}
        </ul>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <Provenance option={option} />
            <LinkChips links={verifyLinks(option)} />
          </div>
          <Button
            size="sm"
            variant={picked ? "sun" : "outline"}
            onClick={() => onPick(option.option_id)}
          >
            {picked ? <Check className="size-4" aria-hidden /> : null}
            {picked ? "Picked" : "Pick"}
          </Button>
        </div>
      </article>
    </li>
  );
}

/** A place to stay: photo, name, rating, distance, price per person. */
export function StayCard({ option, currency, index, picked, onPick }: PickProps): ReactNode {
  const image = optionImage(option);
  const item = option.items[0];
  return (
    <li
      className="rise-in w-[72%] max-w-[260px] shrink-0 snap-start list-none"
      style={{ "--i": index, "--delay": "120ms" } as CSSProperties}
    >
      <article
        aria-label={option.label}
        className={cn(
          "flex h-full flex-col overflow-hidden rounded-[24px] border bg-surface shadow-card transition",
          picked ? "border-sun ring-2 ring-sun/30" : "border-line",
        )}
      >
        <div className="relative aspect-[16/9] bg-surface-sunken">
          {image ? (
            <img src={image} alt={option.label} loading="lazy" className="size-full object-cover" />
          ) : (
            <span className="flex size-full items-center justify-center text-muted">
              <BedDouble className="size-8" aria-hidden />
            </span>
          )}
          <span className="absolute top-2 left-2">
            <Provenance option={option} />
          </span>
        </div>
        <div className="flex flex-1 flex-col gap-2 p-4">
          <h3 className="line-clamp-2 text-sm font-medium text-ink">{option.label}</h3>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            {option.stars !== null && option.stars !== undefined && (
              <span className="inline-flex items-center gap-0.5">
                <Star className="size-3" aria-hidden />
                {option.stars}
              </span>
            )}
            {option.rating !== null && option.rating !== undefined && (
              <span>rated {option.rating.toFixed(1)}</span>
            )}
            {option.km_from_centre !== null && option.km_from_centre !== undefined && (
              <span className="inline-flex items-center gap-0.5">
                <MapPin className="size-3" aria-hidden />
                {option.km_from_centre.toFixed(1)} km from centre
              </span>
            )}
          </p>
          {item?.details && <p className="line-clamp-2 text-xs text-muted">{item.details}</p>}
          <div className="mt-auto flex items-end justify-between gap-2 pt-1">
            <PerPerson option={option} currency={currency} align="left" />
            <LinkChips links={verifyLinks(option)} />
          </div>
          <Button
            size="sm"
            variant={picked ? "sun" : "outline"}
            onClick={() => onPick(option.option_id)}
          >
            {picked ? "Picked" : "Stay here"}
          </Button>
        </div>
      </article>
    </li>
  );
}

/** Things to do: tap to toggle, then continue (or skip). */
export function ActivityPicker({
  options,
  currency,
  initial,
  onDone,
}: {
  options: readonly OptionResponse[];
  currency: string;
  initial: readonly string[];
  onDone: (ids: string[]) => void;
}): ReactNode {
  const [chosen, setChosen] = useState<string[]>([...initial]);
  const toggle = (id: string): void =>
    setChosen((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap gap-2" aria-label="Things to do">
        {options.map((option, index) => {
          const on = chosen.includes(option.option_id);
          return (
            <li
              key={option.option_id}
              className="pop list-none"
              style={{ "--i": index, "--delay": "120ms" } as CSSProperties}
            >
              <button
                type="button"
                aria-pressed={on}
                onClick={() => toggle(option.option_id)}
                className={cn(
                  "rounded-full border px-3.5 py-1.5 text-left text-sm transition active:scale-[0.97]",
                  on
                    ? "border-sun bg-sun text-sun-ink"
                    : "border-line bg-surface text-ink hover:border-ink/25",
                )}
              >
                {option.label}
                <span className={cn("ticket-mono ml-2 text-xs", on ? "" : "text-muted")}>
                  {formatMoney(option.per_person_minor, currency)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="flex gap-2">
        <Button size="sm" variant="sun" onClick={() => onDone(chosen)} disabled={!chosen.length}>
          Add {chosen.length || ""} to the trip
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onDone([])}>
          Skip
        </Button>
      </div>
    </div>
  );
}
