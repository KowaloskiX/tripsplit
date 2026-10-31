import { createFileRoute, redirect } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Panel } from "@/components/ui/panel";
import { sessionQueryOptions } from "@/features/auth";
import { JoinTripForm } from "@/features/trips";

export const Route = createFileRoute("/join/$inviteCode")({
  ssr: false,
  // Signed-out friends go to sign in (or register) and come straight back here.
  beforeLoad: async ({ context, location }) => {
    const session = await context.queryClient.ensureQueryData(sessionQueryOptions());
    if (!session.user) throw redirect({ to: "/login", search: { redirect: location.href } });
  },
  component: JoinPage,
});

function JoinPage(): ReactNode {
  const { inviteCode } = Route.useParams();
  return (
    <div className="mx-auto w-full max-w-sm px-6 py-16 lg:py-24">
      <p className="eyebrow">invite</p>
      <h1 className="display mt-3 text-5xl text-ink">You are invited on a trip</h1>
      <p className="mt-3 text-sm text-muted">Tell the group what to call you.</p>
      <Panel className="mt-7 p-6">
        <JoinTripForm inviteCode={inviteCode} />
      </Panel>
    </div>
  );
}
