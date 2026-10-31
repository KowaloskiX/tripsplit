import { createFileRoute, redirect } from "@tanstack/react-router";

import { sessionQueryOptions } from "@/features/auth";
import { WalletPage } from "@/features/wallet";

export const Route = createFileRoute("/wallet")({
  // The wallet is private and the session is a browser cookie — client-only.
  ssr: false,
  beforeLoad: async ({ context, location }) => {
    const session = await context.queryClient.ensureQueryData(sessionQueryOptions());
    if (!session.user) throw redirect({ to: "/login", search: { redirect: location.href } });
  },
  component: WalletPage,
});
