import { Link } from "@tanstack/react-router";
import { MessagesSquare, RefreshCw, ThumbsUp, Wallet } from "lucide-react";
import { type CSSProperties, type ReactNode, useRef } from "react";

import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Reveal } from "@/components/ui/reveal";
import { useInView } from "@/lib/motion";
import { cn } from "@/lib/utils";

import { StartTripButton } from "./landing-hero";
import { Wordmark } from "./wordmark";

const STEPS = [
  {
    icon: MessagesSquare,
    title: "Propose",
    body: "Say where and when. Get three ready-to-book packages.",
    fill: "bg-pastel-sea",
  },
  {
    icon: ThumbsUp,
    title: "Vote",
    body: "The group picks one in the chat.",
    fill: "bg-pastel-apricot",
  },
  {
    icon: Wallet,
    title: "Pay your share",
    body: "Nothing is bought until everyone has paid.",
    fill: "bg-pastel-blush",
  },
  {
    icon: RefreshCw,
    title: "Go",
    body: "The agent books it, and rebooks if a train falls through.",
    fill: "bg-surface-sunken",
  },
] as const;

function SectionTitle({ id, children }: { id: string; children: ReactNode }): ReactNode {
  return (
    <Reveal>
      <h2
        id={id}
        className="display mx-auto max-w-3xl text-center text-[clamp(2.6rem,6vw,4.2rem)] text-balance text-ink"
      >
        {children}
      </h2>
    </Reveal>
  );
}

export function HowItWorks(): ReactNode {
  return (
    <section
      aria-labelledby="how-heading"
      className="mx-auto max-w-6xl px-4 py-24 sm:px-6 sm:py-32"
    >
      <SectionTitle id="how-heading">How it works</SectionTitle>
      <ol className="mt-14 grid gap-4 sm:mt-20 md:grid-cols-2">
        {STEPS.map((step, index) => (
          <Reveal
            as="li"
            key={step.title}
            index={index % 2}
            className={cn(
              "flex min-h-56 flex-col justify-between rounded-[var(--radius-panel)] p-8 text-pastel-ink sm:p-10",
              step.fill,
              step.fill === "bg-surface-sunken" && "text-ink",
            )}
          >
            <div className="flex items-center justify-between">
              <span className="ticket-mono text-sm">0{index + 1}</span>
              <step.icon className="size-7" strokeWidth={1.5} aria-hidden />
            </div>
            <div>
              <h3 className="text-3xl tracking-[-0.03em] sm:text-4xl">{step.title}</h3>
              <p className="mt-3 max-w-md text-[17px] leading-relaxed opacity-75">{step.body}</p>
            </div>
          </Reveal>
        ))}
      </ol>
    </section>
  );
}

const SHARES = [
  { name: "Ola Nowak", state: "paid" },
  { name: "Kuba Wiśniewski", state: "paid" },
  { name: "Maja Zielińska", state: "paid" },
  { name: "Tomek Lis", state: "paid" },
  { name: "Ewa Kowalska", state: "owes" },
  { name: "Piotr Wójcik", state: "refund" },
] as const;

const SHARE_BADGE = {
  paid: { tone: "success", label: "paid 593 zł" },
  owes: { tone: "warn", label: "owes 593 zł" },
  refund: { tone: "info", label: "refund 59 zł" },
} as const;

export function FairSplit(): ReactNode {
  return (
    <section aria-labelledby="split-heading" className="border-t border-line">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-24 sm:px-6 sm:py-32 lg:grid-cols-2 lg:gap-20">
        <Reveal>
          <h2
            id="split-heading"
            className="display text-[clamp(2.6rem,6vw,4.2rem)] text-balance text-ink"
          >
            Nobody fronts the money
          </h2>
          <p className="mt-6 max-w-lg text-lg leading-relaxed text-muted">
            Price drops or a train changes? Shares re-split and the difference comes back.
          </p>
        </Reveal>

        <SharesFigure />
      </div>
    </section>
  );
}

/** The example shares: the bar fills and the badges pop in once it scrolls into view. */
function SharesFigure(): ReactNode {
  const ref = useRef<HTMLElement>(null);
  const visible = useInView(ref, "0px 0px -15% 0px");
  return (
    <figure
      ref={ref}
      data-visible={visible}
      aria-label="Example: four of six shares paid"
      className="reveal rounded-[var(--radius-panel)] bg-surface-sunken p-6 sm:p-8"
      style={{ "--i": 1 } as CSSProperties}
    >
      <div className="flex items-baseline justify-between">
        <p className="text-2xl tracking-tight text-ink">Shares</p>
        <p className="ticket-mono text-sm text-muted">3 558 zł</p>
      </div>
      <div className="mt-5 flex items-center gap-3">
        <Progress value={visible ? 4 : 0} max={6} tone="success" label="4 of 6 shares paid" />
        <span className="ticket-mono shrink-0 text-sm text-ink">4/6 paid</span>
      </div>
      <ul className="mt-5 space-y-1">
        {SHARES.map((share, index) => (
          <li
            key={share.name}
            className="flex items-center gap-3 rounded-2xl bg-surface px-3 py-2.5"
          >
            <Avatar name={share.name} size="sm" />
            <span className="min-w-0 flex-1 truncate text-[15px] text-ink">{share.name}</span>
            <Badge
              tone={SHARE_BADGE[share.state].tone}
              className="cue pop ticket-mono"
              style={{ "--i": index, "--delay": "450ms" } as CSSProperties}
            >
              {SHARE_BADGE[share.state].label}
            </Badge>
          </li>
        ))}
      </ul>
    </figure>
  );
}

export function ClosingCta(): ReactNode {
  return (
    <section aria-labelledby="cta-heading" className="px-4 pb-16 sm:px-6 sm:pb-24">
      <Reveal className="mx-auto flex max-w-6xl flex-col items-center rounded-[var(--radius-panel)] bg-surface-sunken px-6 py-20 text-center text-ink sm:py-28">
        <h2
          id="cta-heading"
          className="display max-w-3xl text-[clamp(2.6rem,6vw,4.6rem)] text-balance"
        >
          Plan your next trip
        </h2>
        <StartTripButton className="mt-10" />
      </Reveal>
    </section>
  );
}

export function LandingFooter(): ReactNode {
  return (
    <footer className="border-t border-line bg-bg text-ink">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-4 py-10 sm:px-6">
        <Wordmark />
        <Link to="/login" className="text-sm text-muted transition duration-150 hover:text-ink">
          Sign in
        </Link>
      </div>
    </footer>
  );
}
