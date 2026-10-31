import { Link } from "@tanstack/react-router";
import { ArrowRight, Check, TrainFront } from "lucide-react";
import type { ReactNode } from "react";

import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { useSession } from "@/features/auth";

/** Signed in -> straight to your trips; otherwise create an account first. */
export function StartTripButton({ className }: { className?: string }): ReactNode {
  const { user } = useSession();
  return (
    <Button size="lg" asChild className={className}>
      <Link to={user ? "/app" : "/register"}>
        Start a trip
        <ArrowRight className="size-5" aria-hidden />
      </Link>
    </Button>
  );
}

export function LandingHero(): ReactNode {
  return (
    <section aria-labelledby="hero-heading" className="dark overflow-hidden bg-bg text-ink">
      <div className="mx-auto flex max-w-6xl flex-col items-center px-4 pt-16 pb-20 text-center sm:px-6 sm:pt-24 sm:pb-28">
        <p className="eyebrow rounded-full border border-line px-3 py-1">
          A travel agent for your group chat
        </p>
        <h1
          id="hero-heading"
          className="display mt-8 max-w-5xl text-[clamp(3.4rem,10vw,7.5rem)] text-balance"
        >
          From group <span className="accent-word text-lime">chat</span> to{" "}
          <span className="accent-word text-lime">tickets</span>
        </h1>
        <p className="mt-8 max-w-2xl text-lg leading-relaxed text-muted text-balance sm:text-2xl sm:leading-9">
          Tell it where and when. It finds a trip the whole group can afford, collects
          everyone&apos;s share, and books the train and the stay.
        </p>
        <div className="mt-10 flex w-full flex-col items-center gap-3 sm:w-auto sm:flex-row">
          <StartTripButton className="w-full sm:w-auto" />
          <Button variant="outline" size="lg" asChild className="w-full sm:w-auto">
            <Link to="/login">I have an account</Link>
          </Button>
        </div>

        <ChatToTicket />
      </div>
    </section>
  );
}

/** The product in one picture, drawn in HTML: a chat thread turning into a ticket. */
function ChatToTicket(): ReactNode {
  return (
    <figure
      aria-label="Illustration: a group chat about Prague turns into a booked train ticket"
      className="mt-16 grid w-full max-w-4xl items-center gap-6 text-left sm:mt-24 md:grid-cols-[1fr_auto_1fr]"
    >
      <div className="rounded-[32px] border border-line bg-surface p-5 md:-rotate-2">
        <p className="eyebrow">Group chat · 6 people</p>
        <div className="mt-4 space-y-3">
          <ChatLine name="Maja Zielińska" text="Prague in December? 🍻" />
          <ChatLine name="Kuba Mazur" text="In, if it’s under 700 zł" />
          <div className="rounded-2xl rounded-tl-md bg-agent-bg px-4 py-3 ring-1 ring-lime/25">
            <p className="ticket-mono text-[11px] uppercase text-agent-tag">tripsplit agent</p>
            <p className="mt-1 text-[15px] text-agent-fg">
              3 packages from 593 zł each. Vote, then pay your share — I&apos;ll book.
            </p>
          </div>
        </div>
      </div>

      <ArrowRight
        className="mx-auto size-8 rotate-90 text-lime md:rotate-0"
        strokeWidth={1.5}
        aria-hidden
      />

      <div className="relative overflow-hidden rounded-[32px] bg-pastel-sky text-pastel-ink md:rotate-2">
        <div className="flex items-center justify-between px-6 pt-5">
          <span className="ticket-mono text-xs uppercase">Boarding · PKP Intercity</span>
          <TrainFront className="size-5" aria-hidden />
        </div>
        <div className="flex items-end justify-between gap-4 px-6 pt-4 pb-5">
          <div>
            <p className="ticket-mono text-3xl">WAW → PRG</p>
            <p className="ticket-mono mt-1 text-sm">EC 131 · 05 DEC · 06:47</p>
          </div>
          <p className="ticket-mono text-sm">×6</p>
        </div>
        <div className="relative">
          <span className="absolute -left-3 top-1/2 size-6 -translate-y-1/2 rounded-full bg-bg" />
          <span className="absolute -right-3 top-1/2 size-6 -translate-y-1/2 rounded-full bg-bg" />
          <div className="perforation mx-5 [--color-line:rgb(0_0_0/0.35)]" />
        </div>
        <div className="flex items-center justify-between px-6 py-4">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-pastel-ink px-3 py-1 text-xs text-lime">
            <Check className="size-3.5" aria-hidden />
            6/6 paid
          </span>
          <span className="ticket-mono text-lg">593 zł / person</span>
        </div>
      </div>
    </figure>
  );
}

function ChatLine({ name, text }: { name: string; text: string }): ReactNode {
  return (
    <div className="flex items-end gap-2">
      <Avatar name={name} size="sm" />
      <p className="rounded-2xl rounded-bl-md bg-surface-sunken px-3.5 py-2 text-[15px]">{text}</p>
    </div>
  );
}
