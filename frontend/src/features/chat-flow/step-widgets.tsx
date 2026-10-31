import { Check, Copy, Share2, X } from "lucide-react";
import { type CSSProperties, type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { TypingIndicator } from "@/components/ui/typing-indicator";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import type { BriefChip, SupplierTick } from "./from-api";

/** Step 1: what the agent understood, one chip per field; a missing one is highlighted. */
export function BriefChips({ chips }: { chips: readonly BriefChip[] }): ReactNode {
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="What I understood">
      {chips.map((chip, index) => (
        <li
          key={chip.label}
          className={cn(
            "pop list-none rounded-full border px-3 py-1 text-xs",
            chip.value ? "border-line bg-surface text-ink" : "border-warn/50 bg-warn-soft text-ink",
          )}
          style={{ "--i": index } as CSSProperties}
        >
          <span className="text-muted">{chip.label}</span>{" "}
          <span className="font-medium">{chip.value ?? "?"}</span>
        </li>
      ))}
    </ul>
  );
}

/** Answer chips for a question the brief left open. */
export function AnswerChips({
  options,
  onAnswer,
}: {
  options: readonly string[];
  onAnswer: (option: string) => void;
}): ReactNode {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((option, index) => (
        <button
          key={option}
          type="button"
          onClick={() => onAnswer(option)}
          className="pop rounded-full border border-line bg-surface px-3.5 py-1.5 text-sm text-ink transition hover:border-sun active:scale-[0.96]"
          style={{ "--i": index, "--delay": "200ms" } as CSSProperties}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

/** Step 2: every supplier ticked off as its search returns. */
export function SupplierTicks({
  ticks,
  searching,
}: {
  ticks: readonly SupplierTick[];
  searching: boolean;
}): ReactNode {
  return (
    <ul className="space-y-1" aria-label="Suppliers searched">
      {ticks.map((tick) => {
        const ok = tick.outcome === "ok" || tick.outcome === "cached";
        const bad = tick.outcome === "failed" || tick.outcome === "timeout";
        return (
          <li key={tick.id} className="feed-in-right flex items-center gap-2 text-sm">
            <span
              className={cn(
                "inline-flex size-5 items-center justify-center rounded-full",
                ok
                  ? "bg-success-soft text-success"
                  : bad
                    ? "bg-danger-soft text-danger"
                    : "bg-surface-sunken text-muted",
              )}
            >
              {bad ? (
                <X className="size-3" aria-hidden />
              ) : (
                <Check className="size-3" aria-hidden />
              )}
            </span>
            <span className="ticket-mono text-xs text-ink">{tick.line}</span>
          </li>
        );
      })}
      {searching && (
        <li className="flex items-center gap-2 text-sm text-muted">
          <TypingIndicator />
          <span className="text-xs">{ticks.length ? "still searching…" : "asking suppliers…"}</span>
        </li>
      )}
    </ul>
  );
}

/** Step 6: the composed trip with total, per person and whether it fits the budget. */
export type SummaryLine = { id: string; label: string; totalMinor: number };

export function SummaryCard({
  lines,
  travellers,
  currency,
  budgetMinor,
  pending,
  onConfirm,
  onChange,
}: {
  lines: readonly SummaryLine[];
  travellers: number;
  currency: string;
  budgetMinor: number | null;
  pending: boolean;
  onConfirm?: (() => void) | undefined;
  onChange?: ((step: "transport" | "stay") => void) | undefined;
}): ReactNode {
  const total = lines.reduce((sum, line) => sum + line.totalMinor, 0);
  const perPerson = Math.ceil(total / Math.max(travellers, 1));
  const fits = budgetMinor === null || perPerson <= budgetMinor;
  return (
    <section
      aria-label="Your trip"
      className="sheet-up space-y-3 rounded-[28px] border border-line bg-surface p-4 shadow-pop sm:p-5"
    >
      <p className="eyebrow">Your trip</p>
      <ul className="divide-y divide-line">
        {lines.map((line) => (
          <li key={line.id} className="flex items-baseline justify-between gap-3 py-2">
            <span className="min-w-0 truncate text-sm text-ink">{line.label}</span>
            <span className="ticket-mono shrink-0 text-sm text-ink">
              {formatMoney(line.totalMinor, currency)}
            </span>
          </li>
        ))}
      </ul>
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-xs text-muted">
            Total for {travellers} {travellers === 1 ? "person" : "people"}
          </p>
          <p className="ticket-mono text-lg text-ink">{formatMoney(total, currency)}</p>
        </div>
        <div className="text-right">
          <p className="ticket-mono text-2xl text-ink">{formatMoney(perPerson, currency)}</p>
          <p className="text-xs text-muted">per person</p>
        </div>
      </div>
      {budgetMinor !== null && (
        <p
          className={cn(
            "rounded-2xl px-3 py-2 text-xs",
            fits ? "bg-success-soft text-ink" : "bg-warn-soft text-ink",
          )}
        >
          {fits
            ? `Within your budget of ${formatMoney(budgetMinor, currency)} per person.`
            : `${formatMoney(perPerson - budgetMinor, currency)} per person over your budget of ${formatMoney(budgetMinor, currency)}.`}
        </p>
      )}
      {onConfirm && (
        <div className="flex flex-wrap gap-2">
          <Button variant="sun" onClick={onConfirm} disabled={pending}>
            {pending ? "Locking it in…" : "Looks good"}
          </Button>
          {onChange && (
            <>
              <Button variant="ghost" size="sm" onClick={() => onChange("transport")}>
                Change transport
              </Button>
              <Button variant="ghost" size="sm" onClick={() => onChange("stay")}>
                Change stay
              </Button>
            </>
          )}
        </div>
      )}
    </section>
  );
}

function copy(text: string): Promise<void> {
  return navigator.clipboard?.writeText(text) ?? Promise.resolve();
}

/** The invite link with copy + the system share sheet (phones). */
export function InviteShare({ url, title }: { url: string; title: string }): ReactNode {
  const [copied, setCopied] = useState(false);
  const canShare = typeof navigator !== "undefined" && typeof navigator.share === "function";
  return (
    <div className="space-y-2 rounded-[24px] border border-line bg-surface p-4 shadow-card">
      <p className="text-xs text-muted">Send this to your friends:</p>
      <p className="ticket-mono truncate rounded-xl bg-surface-sunken px-3 py-2 text-xs text-ink">
        {url}
      </p>
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() =>
            copy(url)
              .then(() => setCopied(true))
              .catch(() => undefined)
          }
        >
          <Copy className="size-4" aria-hidden />
          {copied ? "Copied" : "Copy link"}
        </Button>
        {canShare && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => navigator.share({ title, url }).catch(() => undefined)}
          >
            <Share2 className="size-4" aria-hidden />
            Share
          </Button>
        )}
      </div>
    </div>
  );
}
