import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Reveal } from "@/components/ui/reveal";

import { StartTripButton } from "./landing-hero";
import { Wordmark } from "./wordmark";

const VALUES = [
  {
    title: "One vote",
    body: "Three ready-to-book packages in the chat. The group picks one.",
  },
  {
    title: "Everyone pays their share",
    body: "Nobody fronts the money. Nothing is bought until every share is in.",
  },
  {
    title: "Booked, and rebooked",
    body: "The agent buys the train and the stay, and finds another if a train falls through.",
  },
] as const;

/** Three short reasons, side by side. */
export function HowItWorks(): ReactNode {
  return (
    <section aria-labelledby="how-heading" className="border-t border-line bg-sand-50 dark:bg-bg">
      <div className="mx-auto max-w-6xl px-4 py-24 sm:px-6 sm:py-28">
        <Reveal>
          <h2
            id="how-heading"
            className="display max-w-xl text-[clamp(2.25rem,4.5vw,3.25rem)] text-ink"
          >
            How it works
          </h2>
        </Reveal>
        <ol className="mt-14 grid gap-10 md:grid-cols-3 md:gap-8">
          {VALUES.map((value, index) => (
            <Reveal as="li" key={value.title} index={index} className="border-t border-line pt-6">
              <span className="text-[13px] tabular-nums text-muted">0{index + 1}</span>
              <h3 className="mt-3 text-xl font-medium text-ink">{value.title}</h3>
              <p className="mt-2 max-w-xs text-[15px] leading-relaxed text-muted">{value.body}</p>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function ClosingCta(): ReactNode {
  return (
    <section aria-labelledby="cta-heading" className="px-4 py-20 sm:px-6 sm:py-24">
      <Reveal className="mx-auto flex max-w-6xl flex-col items-start gap-8 rounded-[var(--radius-panel)] bg-sand-200 px-8 py-14 sm:flex-row sm:items-center sm:justify-between sm:px-12 dark:bg-surface-sunken">
        <h2 id="cta-heading" className="display text-[clamp(2rem,4vw,3rem)] text-balance text-ink">
          Plan your next trip
        </h2>
        <StartTripButton />
      </Reveal>
    </section>
  );
}

export function LandingFooter(): ReactNode {
  return (
    <footer className="border-t border-line bg-bg text-ink">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-4 py-8 sm:px-6">
        <Wordmark className="text-xl" />
        <div className="flex items-center gap-6 text-sm text-muted">
          <span>© {new Date().getFullYear()} tripsplit</span>
          <Link to="/login" className="transition duration-150 hover:text-ink">
            Sign in
          </Link>
        </div>
      </div>
    </footer>
  );
}
