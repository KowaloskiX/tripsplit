import type { CSSProperties, ReactNode } from "react";

import { ConfettiBurst } from "@/components/ui/confetti-burst";
import { DigitRoll } from "@/components/ui/number-roll";
import { Stamp } from "@/components/ui/stamp";
import { TypingIndicator } from "@/components/ui/typing-indicator";
import { useArrivedAt } from "@/lib/motion";

import { handedOff, type PhoneState, type PhonesPhase, progressOf } from "./model";
import { PhoneFrame } from "./phone-frame";

type GroupPhonesProps = {
  phones: readonly PhoneState[];
  phase: PhonesPhase;
  currency?: string;
};

function Counter({
  phones,
  phase,
}: {
  phones: readonly PhoneState[];
  phase: PhonesPhase;
}): ReactNode {
  const { done, total, unit } = progressOf(phones, phase);
  const handoff = handedOff(phones, phase);
  const burst = useArrivedAt(handoff, true, 2600);
  return (
    <div className="relative col-span-full flex flex-col items-center justify-center py-2 text-center lg:col-span-1 lg:min-w-[13rem] lg:py-0">
      <p
        className="display text-[clamp(4.5rem,11vw,8rem)] leading-none text-ink"
        aria-live="polite"
      >
        <span className="sr-only">
          {done} of {total} {unit}
        </span>
        <span aria-hidden>
          <DigitRoll value={done} className="font-sans tracking-normal" />
          <span className="text-muted">/{total}</span>
        </span>
      </p>
      <p className="eyebrow -mt-1">{unit}</p>
      {handoff && (
        <div className="mt-4 flex flex-col items-center gap-3">
          <span className="relative">
            {burst && <ConfettiBurst count={30} spread={180} />}
            <Stamp tone="sun" rotate={-6}>
              {total}/{total} paid
            </Stamp>
          </span>
          <p
            className="rise-in inline-flex items-center gap-2 rounded-full bg-agent-bg px-4 py-2 text-sm text-agent-fg"
            style={{ "--delay": "500ms" } as CSSProperties}
          >
            <TypingIndicator className="text-agent-tag" />
            Agent is booking…
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * Demo mode: every member's phone side by side, votes and payments arriving one after another,
 * a big counter in the middle and, at the last share, the hand-off to the agent.
 */
export function GroupPhones({ phones, phase, currency = "PLN" }: GroupPhonesProps): ReactNode {
  const top = phones.slice(0, Math.ceil(phones.length / 2));
  const bottom = phones.slice(top.length);
  const phone = (state: PhoneState, index: number): ReactNode => (
    <div key={state.name} className="rise-in" style={{ "--i": index } as CSSProperties}>
      <PhoneFrame phone={state} phase={phase} currency={currency} />
    </div>
  );
  return (
    <section
      aria-label="The group's phones"
      className="dark rounded-[40px] bg-bg px-4 py-6 text-ink sm:px-8 sm:py-8"
    >
      {/* Phone: counter on top, phones in two rows of three. Desktop: one row, the counter
          in the middle of the group. */}
      <div className="grid grid-cols-3 items-center gap-3 sm:gap-5 lg:grid-cols-[repeat(3,minmax(0,1fr))_auto_repeat(3,minmax(0,1fr))] lg:gap-4">
        <div className="order-first col-span-full lg:hidden">
          <Counter phones={phones} phase={phase} />
        </div>
        {top.map(phone)}
        <div className="hidden lg:block">
          <Counter phones={phones} phase={phase} />
        </div>
        {bottom.map((state, index) => phone(state, index + top.length))}
      </div>
    </section>
  );
}
