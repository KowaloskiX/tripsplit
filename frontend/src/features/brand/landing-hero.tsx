import { Link } from "@tanstack/react-router";
import { ArrowRight, BedDouble, Check, TrainFront } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import { Avatar } from "@/components/ui/avatar";
import { BackgroundVideo } from "@/components/ui/background-video";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Reveal } from "@/components/ui/reveal";
import { useSession } from "@/features/auth";

/** Signed in -> straight to your trips; otherwise create an account first. */
export function StartTripButton({ className }: { className?: string }): ReactNode {
  const { user } = useSession();
  return (
    <Button variant="sun" size="lg" asChild className={className}>
      <Link to={user ? "/plan" : "/register"}>Start a trip</Link>
    </Button>
  );
}

/** `style` for an element that starts `ms` into the entrance. */
function at(ms: number): CSSProperties {
  return { "--delay": `${ms}ms` } as CSSProperties;
}

/** "From group chat to tickets" — the one serif headline. */
export function HeroHeadline({ id, className }: { id?: string; className?: string }): ReactNode {
  return (
    <h1
      id={id}
      className={`display rise-in text-[clamp(2.75rem,6vw,4.75rem)] text-balance text-ink ${className ?? ""}`}
    >
      From group chat to tickets
    </h1>
  );
}

export function LandingHero(): ReactNode {
  return (
    <section aria-labelledby="hero-heading" className="relative overflow-hidden bg-bg text-ink">
      <BackgroundVideo src="/media/hero-forest.mp4" poster="/media/hero-forest.jpg" />
      {/* Keeps the headline readable over the footage: solid page colour on the text side. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-gradient-to-b from-bg/90 via-bg/75 to-bg lg:bg-gradient-to-r lg:from-bg lg:via-bg/85 lg:to-bg/30"
      />
      <div className="relative mx-auto grid max-w-6xl items-center gap-14 px-4 pt-14 pb-20 sm:px-6 sm:pt-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-16 lg:pt-28 lg:pb-32">
        <div className="max-w-xl">
          <p
            className="rise-in inline-flex items-center gap-2 rounded-[var(--radius-control)] border border-line bg-surface-sunken px-3 py-1.5 text-[13px] text-muted"
            style={at(0)}
          >
            <span aria-hidden className="size-1.5 rounded-full bg-sand-600" />
            Group trips, without the spreadsheet
          </p>
          <HeroHeadline id="hero-heading" className="mt-6" />
          <p className="rise-in mt-6 max-w-md text-lg leading-relaxed text-muted" style={at(120)}>
            Say where and when. Everyone pays their own share, then the agent books the train and
            the stay.
          </p>
          <div
            className="rise-in mt-10 flex flex-wrap items-center gap-x-6 gap-y-3"
            style={at(220)}
          >
            <StartTripButton />
            <Link
              to="/login"
              className="group inline-flex items-center gap-1.5 text-[15px] font-medium text-ink underline-offset-4 hover:underline"
            >
              I have an account
              <ArrowRight
                className="size-4 transition duration-200 group-hover:translate-x-0.5"
                aria-hidden
              />
            </Link>
          </div>
        </div>

        <ProductVisual />
      </div>
    </section>
  );
}

/** One calm product shot drawn in HTML: the trip room's package, shares and ticket. */
function ProductVisual(): ReactNode {
  return (
    <figure
      className="rise-in relative rounded-[calc(var(--radius-panel)+8px)] bg-sand-200 p-3 sm:p-5 dark:bg-surface-sunken"
      style={at(280)}
    >
      <figcaption className="sr-only">
        Illustration: a trip room where six friends picked a package, paid their shares and got the
        train booked
      </figcaption>
      <div className="rounded-[var(--radius-panel)] border border-line bg-surface p-5 shadow-card sm:p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="display text-3xl text-ink">Weekend in Prague</p>
            <p className="mt-1 text-[13px] text-muted">5 – 7 Dec · 6 people</p>
          </div>
          <div className="flex -space-x-2">
            {["Maja Zielińska", "Kuba Mazur", "Ola Nowak"].map((name) => (
              <Avatar key={name} name={name} size="sm" className="ring-2 ring-surface" />
            ))}
          </div>
        </div>

        <div className="mt-6 space-y-2.5 rounded-[var(--radius-control)] border border-line p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[15px] font-semibold text-ink">Comfort</p>
            <p className="text-[15px] font-semibold tabular-nums text-ink">593 zł / person</p>
          </div>
          <p className="flex items-center gap-2 text-sm text-muted">
            <TrainFront className="size-3.5" aria-hidden /> PKP Intercity · Fri 06:47
          </p>
          <p className="flex items-center gap-2 text-sm text-muted">
            <BedDouble className="size-3.5" aria-hidden /> Apartment in Vinohrady
          </p>
        </div>

        <div className="mt-5">
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-ink">Shares</span>
            <span className="tabular-nums text-muted">6/6 paid</span>
          </div>
          <Progress value={6} max={6} tone="success" label="6 of 6 shares paid" className="mt-2" />
        </div>

        <div className="mt-5 flex items-center gap-3 rounded-[var(--radius-control)] bg-success-soft px-4 py-3 text-success">
          <Check className="size-4 shrink-0" aria-hidden />
          <p className="min-w-0 flex-1 text-sm">Train and stay booked</p>
          <span className="ticket-mono text-xs">PNR K7Q2XD</span>
        </div>
      </div>

      <div className="absolute -right-3 -bottom-6 hidden max-w-[15rem] rounded-[var(--radius-panel)] border border-line bg-surface px-4 py-3 shadow-pop sm:block lg:-right-6">
        <p className="text-xs font-medium text-agent-tag">tripsplit agent</p>
        <p className="mt-0.5 text-[13px] leading-snug text-ink">
          Your train is late. I rebooked the 08:15, no extra cost.
        </p>
      </div>
    </figure>
  );
}

/** A chat thread turning into a ticket, drawn in HTML; plays once when scrolled into view. */
export function ChatToTicket(): ReactNode {
  return (
    <Reveal
      as="figure"
      className="mt-16 grid w-full max-w-4xl items-center gap-6 text-left sm:mt-20 md:grid-cols-[1fr_auto_1fr]"
    >
      <figcaption className="sr-only">
        Illustration: a group chat about Prague turns into a booked train ticket
      </figcaption>
      <div className="rounded-[var(--radius-panel)] border border-line bg-surface p-5 shadow-card">
        <p className="eyebrow">Group chat</p>
        <div className="mt-4 space-y-3">
          <ChatLine name="Maja Zielińska" text="Prague in December?" delayMs={250} />
          <ChatLine name="Kuba Mazur" text="In, if it’s under 700 zł" delayMs={600} />
          <div
            className="cue bubble-in rounded-2xl rounded-tl-md bg-agent-bg px-4 py-3 ring-1 ring-line"
            style={at(950)}
          >
            <p className="text-xs font-medium text-agent-tag">tripsplit agent</p>
            <p className="mt-1 text-[15px] text-agent-fg">
              3 packages from 593 zł each. Vote, then pay your share and I&apos;ll book.
            </p>
          </div>
        </div>
      </div>

      <ArrowRight
        className="mx-auto size-6 rotate-90 text-muted md:rotate-0"
        strokeWidth={1.5}
        aria-hidden
      />

      <div
        className="cue rise-in rounded-[var(--radius-panel)] bg-pastel-sea p-6 text-pastel-ink"
        style={at(1200)}
      >
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted">PKP Intercity</span>
          <TrainFront className="size-5" aria-hidden />
        </div>
        <p className="mt-4 text-3xl tracking-tight">WAW → PRG</p>
        <p className="mt-1 text-sm text-muted">EC 131 · 05 Dec · 06:47 · ×6</p>
        <div className="mt-5 flex items-center justify-between border-t border-pastel-ink/10 pt-4">
          <span className="inline-flex items-center gap-1.5 text-sm text-success">
            <Check className="size-4" aria-hidden /> 6/6 paid
          </span>
          <span className="text-sm tabular-nums">593 zł / person</span>
        </div>
      </div>
    </Reveal>
  );
}

function ChatLine({
  name,
  text,
  delayMs,
}: {
  name: string;
  text: string;
  delayMs: number;
}): ReactNode {
  return (
    <div className="cue bubble-in flex items-end gap-2" style={at(delayMs)}>
      <Avatar name={name} size="sm" />
      <p className="rounded-2xl rounded-bl-md bg-surface-sunken px-3.5 py-2 text-[15px]">{text}</p>
    </div>
  );
}
