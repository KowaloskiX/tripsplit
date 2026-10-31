import { createFileRoute, notFound } from "@tanstack/react-router";

import { MotionShowcase } from "@/features/showcase";

export const Route = createFileRoute("/dev/motion")({
  // A rehearsal page for the demo: every animation on fake data, no backend needed.
  beforeLoad: () => {
    if (!import.meta.env.DEV) throw notFound();
  },
  ssr: false,
  component: MotionShowcase,
});
