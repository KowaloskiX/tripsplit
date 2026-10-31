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
    body: "Say where and when. The agent comes back with three ready-to-buy packages: transport, a stay and something to do.",
    fill: "bg-pastel-sky",
  },
  {
    icon: ThumbsUp,
    title: "Vote",
    body: "Everyone votes in the chat. Packages over the group's budget are flagged.",
    fill: "bg-pastel-lime",
  },
  {
    icon: Wallet,
    title: "Everyone pays their share",
    body: "Each person pays only their part. The agent waits until every share is in before it spends a złoty.",
    fill: "bg-pastel-blush",
  },
  {
    icon: RefreshCw,
    title: "The agent books and rebooks",
    body: "It buys the tickets on the supplier's own site. Train running late? It finds the next one and re-splits the cost.",
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
      <SectionTitle id="how-heading">
        How it <span className="accent-word">works</span>
      </SectionTitle>
      <ol className="mt-14 grid gap-4 sm:mt-20 md:grid-cols-2">
        {STEPS.map((step, index) => (
          <Reveal
            as="li"
            key={step.title}
            index={index % 2}
            className={cn(
              "flex min-h-72 flex-col justify-between rounded-[40px] p-8 text-pastel-ink sm:p-10",
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
          <p className="eyebrow">Nobody fronts the money</p>
          <h2
            id="split-heading"
            className="display mt-5 text-[clamp(2.6rem,6vw,4.2rem)] text-balance text-ink"
          >
            No more &ldquo;I&apos;ll pay, <span className="accent-word">send me a BLIK</span>{" "}
            later&rdquo;
          </h2>
          <p className="mt-6 max-w-lg text-lg leading-relaxed text-muted">
            The agent books only once every share is paid, so no one spends weeks chasing friends.
            If the price drops or a train gets replaced, it re-splits and refunds the difference.
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
      className="reveal rounded-[40px] bg-surface-sunken p-6 sm:p-8"
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
      <Reveal className="dark mx-auto flex max-w-6xl flex-col items-center rounded-[48px] bg-bg px-6 py-20 text-center text-ink sm:rounded-[60px] sm:py-28">
        <h2
          id="cta-heading"
          className="display max-w-3xl text-[clamp(2.6rem,6vw,4.6rem)] text-balance"
        >
          Plan your next <span className="accent-word text-lime">trip</span>
        </h2>
        <p className="mt-5 max-w-md text-lg text-muted">
          Create a trip, share the link in the group chat, and the agent handles the rest.
        </p>
        <StartTripButton className="mt-10" />
      </Reveal>
    </section>
  );
}

export function LandingFooter(): ReactNode {
  return (
    <footer className="dark bg-bg text-ink">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:grid-cols-[1fr_auto_auto] sm:gap-20 sm:px-6">
        <div>
          <Wordmark />
          <p className="mt-4 max-w-xs text-sm leading-relaxed text-muted">
            From group chat to tickets: planned, paid and booked in one place.
          </p>
        </div>
        <nav aria-label="Product" className="text-sm">
          <p className="eyebrow">Product</p>
          <ul className="mt-4 space-y-2.5">
            <li>
              <Link to="/register" className="transition duration-150 hover:text-lime">
                Start a trip
              </Link>
            </li>
            <li>
              <Link to="/login" className="transition duration-150 hover:text-lime">
                Sign in
              </Link>
            </li>
          </ul>
        </nav>
        <div className="text-sm">
          <p className="eyebrow">Promise</p>
          <ul className="mt-4 space-y-2.5 text-ink">
            <li>Nobody fronts the money</li>
            <li>Nothing bought without approval</li>
          </ul>
        </div>
      </div>
      <div className="border-t border-line">
        <p className="ticket-mono mx-auto max-w-6xl px-4 py-6 text-xs text-muted sm:px-6">
          © 2026 tripsplit
        </p>
      </div>
    </footer>
  );
}
