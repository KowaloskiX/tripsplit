import { Check, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { Avatar } from "@/components/ui/avatar";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import type { PhoneState, PhonesPhase } from "./model";

function Action({
  phone,
  phase,
  currency,
}: {
  phone: PhoneState;
  phase: PhonesPhase;
  currency: string;
}): ReactNode {
  const amount = formatMoney(phone.amount, currency);
  if (phase === "voting") {
    return phone.voted_for ? (
      <span className="pop flex items-center justify-center gap-1 truncate rounded-full bg-sun px-2 py-1.5 text-[11px] font-medium text-sun-ink">
        <Check className="size-3 shrink-0" strokeWidth={3} aria-hidden />
        <span className="truncate" title={phone.voted_for}>
          Voted<span className="sr-only"> for {phone.voted_for}</span>
        </span>
      </span>
    ) : (
      <span className="flex items-center justify-center rounded-full border border-ink/20 px-2 py-1.5 text-[11px] text-ink">
        Vote
      </span>
    );
  }
  return phone.paid ? (
    <span className="pop flex items-center justify-center gap-1 rounded-full bg-success-soft px-2 py-1.5 text-[11px] font-medium text-success">
      <Check className="size-3" strokeWidth={3} aria-hidden />
      Paid<span className="hidden sm:inline"> {amount}</span>
    </span>
  ) : (
    <span className="flex items-center justify-center rounded-full bg-ink px-2 py-1.5 text-[11px] font-medium text-bg">
      Pay<span className="hidden sm:inline"> {amount}</span>
    </span>
  );
}

type PhoneFrameProps = { phone: PhoneState; phase: PhonesPhase; currency: string };

/** One member's phone: their face, the last message they see, and their vote / pay button. */
export function PhoneFrame({ phone, phase, currency }: PhoneFrameProps): ReactNode {
  const settled = phase === "voting" ? phone.voted_for !== null : phone.paid;
  // A new key whenever this member acts remounts the action, so the phone nudges and pops.
  const actionKey = `${phase}-${phone.voted_for ?? ""}-${phone.paid}`;
  return (
    <article
      aria-label={`${phone.name}'s phone`}
      className={cn(
        "relative mx-auto flex aspect-[9/16] w-full max-w-[11rem] flex-col overflow-hidden rounded-[22px] border-4 sm:rounded-[var(--radius-panel)] sm:border-[5px] border-[#2b2b2b] bg-surface shadow-pop transition-shadow duration-500",
        settled && "ring-2 ring-sun ring-offset-2 ring-offset-bg",
      )}
    >
      <span aria-hidden className="mx-auto mt-1.5 h-3 w-10 shrink-0 rounded-full bg-black" />
      <div className="flex items-center gap-1.5 border-b border-line px-2 pt-2 pb-1.5 sm:gap-2 sm:px-3">
        <Avatar name={phone.name} size="sm" className="size-6 ring-0 sm:size-7" />
        <span className="min-w-0 truncate text-[11px] font-medium text-ink sm:text-xs">
          {phone.name.split(" ")[0]}
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col justify-end gap-1.5 overflow-hidden px-2 py-2 sm:px-2.5">
        <div className="hidden items-start gap-1.5 sm:flex">
          <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-agent-bg text-agent-tag">
            <Sparkles className="size-2.5" aria-hidden />
          </span>
          <p className="rounded-2xl rounded-tl-sm bg-agent-bg px-2.5 py-1.5 text-[10px] leading-snug text-agent-fg">
            {phase === "voting" ? "Vote 👇" : "Your share 👇"}
          </p>
        </div>
        {phone.last_message && (
          <p
            key={phone.last_message}
            className="feed-in-right ml-auto line-clamp-2 max-w-[90%] rounded-2xl rounded-br-sm bg-pastel-sea px-2.5 py-1.5 text-[10px] leading-snug text-pastel-ink"
          >
            {phone.last_message}
          </p>
        )}
      </div>
      <div key={actionKey} className="phone-nudge shrink-0 px-2 pb-2.5 sm:px-2.5 sm:pb-3">
        <Action phone={phone} phase={phase} currency={currency} />
      </div>
    </article>
  );
}
