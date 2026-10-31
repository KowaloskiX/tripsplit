import { Link } from "@tanstack/react-router";
import { ArrowRight, Check, TrainFront } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Reveal } from "@/components/ui/reveal";
import { TypingIndicator } from "@/components/ui/typing-indicator";
import { useSession } from "@/features/auth";

/** Signed in -> straight to your trips; otherwise create an account first. */
export function StartTripButton({ className }: { className?: string }): ReactNode {
  const { user } = useSession();
  return (
    <Button size="lg" asChild className={className}>
      <Link to={user ? "/plan" : "/register"}>
        Start a trip
        <ArrowRight className="size-5" aria-hidden />
      </Link>
    </Button>
  );
}

/** One staggered word of the headline; `--i` orders the cascade. */
function Word({
  index,
  children,
  className,
}: {
  index: number;
  children: ReactNode;
  className?: string;
}): ReactNode {
  return (
    <span className={`word-rise ${className ?? ""}`} style={{ "--i": index } as CSSProperties}>
      {children}
    </span>
  );
}

/** `style` for an element that starts `ms` into the illustration's choreography. */
function at(ms: number): CSSProperties {
  return { "--delay": `${ms}ms` } as CSSProperties;
}

/** "From group chat to tickets", one word at a time. */
export function HeroHeadline({ id }: { id?: string }): ReactNode {
  return (
    <h1 id={id} className="display mt-8 max-w-5xl text-[clamp(3.4rem,10vw,7.5rem)] text-balance">
      <Word index={0}>From</Word> <Word index={1}>group</Word>{" "}
      <Word index={2} className="accent-word text-lime">
        chat
      </Word>{" "}
      <Word index={3}>to</Word>{" "}
      <Word index={4} className="accent-word text-lime">
        tickets
      </Word>
    </h1>
  );
}

export function LandingHero(): ReactNode {
  return (
    <section aria-labelledby="hero-heading" className="dark overflow-hidden bg-bg text-ink">
      <div className="mx-auto flex max-w-6xl flex-col items-center px-4 pt-16 pb-20 text-center sm:px-6 sm:pt-24 sm:pb-28">
        <p className="eyebrow rise-in rounded-full border border-line px-3 py-1">
          A travel agent for your group chat
        </p>
        <HeroHeadline id="hero-heading" />
        <p
          className="rise-in mt-8 max-w-2xl text-lg leading-relaxed text-muted text-balance sm:text-2xl sm:leading-9"
          style={at(560)}
        >
          Tell it where and when. It finds a trip the whole group can afford, collects
          everyone&apos;s share, and books the train and the stay.
        </p>
        <div
          className="rise-in mt-10 flex w-full flex-col items-center gap-3 sm:w-auto sm:flex-row"
          style={at(700)}
        >
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

/** A chat thread turning into a ticket, drawn in HTML; plays once when scrolled into view. */
export function ChatToTicket(): ReactNode {
  return (
    <Reveal
      as="figure"
      className="mt-16 grid w-full max-w-4xl items-center gap-6 text-left sm:mt-24 md:grid-cols-[1fr_auto_1fr]"
    >
      <figcaption className="sr-only">
        Illustration: a group chat about Prague turns into a booked train ticket
      </figcaption>
      <div className="parallax [--parallax:-18px]">
        <div className="rounded-[32px] border border-line bg-surface p-5 md:-rotate-2">
          <p className="eyebrow">Group chat · 6 people</p>
          <div className="mt-4 space-y-3">
            <ChatLine name="Maja Zielińska" text="Prague in December? 🍻" delayMs={250} />
            <ChatLine name="Kuba Mazur" text="In, if it’s under 700 zł" delayMs={850} />
            <div className="relative">
              <span
                className="cue typing-window absolute top-0 left-0 inline-flex h-11 items-center rounded-2xl rounded-tl-md bg-agent-bg px-4 text-agent-tag ring-1 ring-lime/25"
                style={{ ...at(1350), "--duration": "900ms" } as CSSProperties}
              >
                <TypingIndicator />
              </span>
              <div
                className="cue bubble-in rounded-2xl rounded-tl-md bg-agent-bg px-4 py-3 ring-1 ring-lime/25"
                style={at(2200)}
              >
                <p className="ticket-mono text-[11px] uppercase text-agent-tag">tripsplit agent</p>
                <p className="mt-1 text-[15px] text-agent-fg">
                  3 packages from 593 zł each. Vote, then pay your share and I&apos;ll book.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <span className="cue rise-in mx-auto" style={at(2600)}>
        <ArrowRight
          className="size-8 rotate-90 text-lime md:rotate-0"
          strokeWidth={1.5}
          aria-hidden
        />
      </span>

      <div className="parallax [--parallax:-48px]">
        <div className="md:rotate-2">
          {/* The printer's mouth the ticket feeds out of. */}
          <div
            aria-hidden
            className="relative z-10 mx-1 h-2.5 rounded-full bg-surface-sunken ring-1 ring-line"
          />
          <div className="-mt-1.5 overflow-hidden px-1 pb-4">
            <div className="cue ticket-print text-pastel-ink" style={at(2850)}>
              <div className="rounded-t-[32px] bg-pastel-sky">
                <div className="flex items-center justify-between px-6 pt-6">
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
                <div className="perforation mx-5 [--color-line:rgb(0_0_0/0.35)]" />
              </div>
              <div
                className="cue stub-tear relative rounded-b-[32px] bg-pastel-sky"
                style={at(4000)}
              >
                <span className="absolute -top-3 -left-3 size-6 rounded-full bg-bg" />
                <span className="absolute -top-3 -right-3 size-6 rounded-full bg-bg" />
                <div className="flex items-center justify-between px-6 py-4">
                  <span
                    className="cue pop inline-flex items-center gap-1.5 rounded-full bg-pastel-ink px-3 py-1 text-xs text-lime"
                    style={at(4300)}
                  >
                    <Check className="size-3.5" aria-hidden />
                    6/6 paid
                  </span>
                  <span className="ticket-mono text-lg">593 zł / person</span>
                </div>
              </div>
            </div>
          </div>
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
