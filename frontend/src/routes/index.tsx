import { createFileRoute, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { SystemReadout } from "@/features/system";

export const Route = createFileRoute("/")({
  component: LandingPage,
});

function LandingPage(): ReactNode {
  return (
    <div className="mx-auto grid max-w-5xl gap-12 px-6 py-16 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-14 lg:py-24">
      <section>
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-accent">tripsplit</p>
        <h1 className="mt-4 max-w-xl font-mono text-4xl leading-[1.08] tracking-tight text-ink sm:text-5xl">
          From group chat
          <br />
          to booked tickets.
        </h1>
        <p className="mt-5 max-w-md text-[15px] leading-relaxed text-muted">
          An agent joins your group, proposes ready-made trip packages, collects votes and each
          person&apos;s share, then books the train, the stay and the activities — and keeps an eye
          on the trip until the end.
        </p>

        <div className="mt-8 flex flex-wrap gap-2.5">
          <Button asChild>
            <Link to="/register">Create account</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link to="/login">Sign in</Link>
          </Button>
        </div>

        <p className="mt-6 font-mono text-[11px] text-muted">
          Create an account, start a trip, invite your friends with a link.
        </p>
      </section>

      <aside className="lg:pt-14">
        <SystemReadout />
      </aside>
    </div>
  );
}
