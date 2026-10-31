import { createFileRoute } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { ClosingCta, HowItWorks, LandingHero } from "@/features/brand";

export const Route = createFileRoute("/")({
  component: LandingPage,
});

function LandingPage(): ReactNode {
  return (
    <div className="bg-surface">
      <LandingHero />
      <HowItWorks />
      <ClosingCta />
    </div>
  );
}
