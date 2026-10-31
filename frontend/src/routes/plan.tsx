import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { z } from "zod";

import { sessionQueryOptions } from "@/features/auth";
import { QuickPlanFlow } from "@/features/quick-plan";

export const Route = createFileRoute("/plan")({
  // The brief creates a trip for the signed-in user; the session is a browser cookie.
  ssr: false,
  validateSearch: z.object({ trip: z.string().optional() }),
  beforeLoad: async ({ context, location }) => {
    const session = await context.queryClient.ensureQueryData(sessionQueryOptions());
    if (!session.user) throw redirect({ to: "/login", search: { redirect: location.href } });
  },
  component: PlanPage,
});

function PlanPage(): ReactNode {
  const { trip } = Route.useSearch();
  const navigate = useNavigate();
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 lg:py-14">
      <QuickPlanFlow
        tripId={trip}
        onTrip={(tripId) => navigate({ to: "/plan", search: { trip: tripId } })}
        onOpenRoom={(tripId) => navigate({ to: "/t/$tripId", params: { tripId } })}
      />
    </div>
  );
}
