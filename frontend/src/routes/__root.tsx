import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  HeadContent,
  Link,
  Outlet,
  Scripts,
  useRouterState,
} from "@tanstack/react-router";
import { type ReactNode, useEffect, useState } from "react";
import { RouteFocus } from "@/components/ui/route-announcer";
import { Toaster } from "@/components/ui/toaster";
import { SessionNav } from "@/features/auth";
import { LandingFooter, Wordmark } from "@/features/brand";
import { THEME_INIT_SCRIPT, ThemeToggle } from "@/features/theme";
import { HeaderWalletChip } from "@/features/wallet";
import { cn } from "@/lib/utils";
import appCss from "@/styles/app.css?url";

const MAIN_REGION_ID = "main-content";

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "Razor Trip: from group chat to tickets" },
      {
        name: "description",
        content:
          "An agent joins your group chat, proposes trip packages, collects votes and everyone's share, then books the train and the stay, and rebooks if the train is late.",
      },
    ],
    // Runs before the first paint, so a dark-mode user never sees a light flash. Declared
    // through the router's head API rather than injected into the shell: a raw <script> in
    // the shell markup broke hydration (React attached no handlers at all).
    scripts: [{ children: THEME_INIT_SCRIPT }],
    links: [
      { rel: "stylesheet", href: appCss },
      // An SVG favicon scales to every size and needs no PNG generation step. Without it every
      // page load ends with a 404 in the console.
      { rel: "icon", href: "/favicon.svg", type: "image/svg+xml" },
    ],
  }),
  shellComponent: RootDocument,
  component: RootLayout,
});

function RootDocument({ children }: { children: ReactNode }): ReactNode {
  return (
    // `suppressHydrationWarning`: THEME_INIT_SCRIPT adds the `dark` class to <html> before
    // React hydrates — on purpose, to avoid a light flash. It applies to this element's own
    // attributes only, so mismatches anywhere below are still reported.
    <html lang="en" suppressHydrationWarning>
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootLayout(): ReactNode {
  const { queryClient } = Route.useRouteContext();
  return (
    <QueryClientProvider client={queryClient}>
      <RouteFocus targetId={MAIN_REGION_ID} />
      <div className="flex min-h-dvh flex-col">
        {/* Visible only when focused: a keyboard user should not have to tab through the whole
            header on every page to reach the content. */}
        <a
          href={`#${MAIN_REGION_ID}`}
          className="sr-only rounded-full bg-accent px-3 py-2 text-sm text-accent-ink focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50"
        >
          Skip to content
        </a>
        <SiteHeader />
        {/* `tabIndex={-1}` so RouteFocus can focus it; it stays out of the tab order. */}
        <main id={MAIN_REGION_ID} tabIndex={-1} className="flex-1 focus:outline-none">
          <Outlet />
        </main>
        <SiteFooter />
      </div>
      <Toaster />
    </QueryClientProvider>
  );
}

function useScrolled(threshold = 8): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const read = (): void => setScrolled(window.scrollY > threshold);
    read();
    window.addEventListener("scroll", read, { passive: true });
    return () => window.removeEventListener("scroll", read);
  }, [threshold]);
  return scrolled;
}

function SiteHeader(): ReactNode {
  const onLanding = useRouterState({ select: (state) => state.location.pathname === "/" });
  const scrolled = useScrolled();
  // Over the landing footage the bar is see-through with light text (a `.dark` subtree);
  // everywhere else, and once the page scrolls, it floats as a frosted rounded bar.
  const overVideo = onLanding && !scrolled;
  return (
    <header
      className={cn(
        "vt-header top-0 z-30 px-3 pt-3 sm:px-4",
        onLanding ? "fixed inset-x-0" : "sticky",
      )}
    >
      <div
        className={cn(
          "mx-auto flex max-w-6xl items-center justify-between gap-3 rounded-[var(--radius-panel)] border px-4 py-2.5 text-ink transition-[background-color,border-color,box-shadow] duration-300 sm:px-5",
          overVideo
            ? "dark border-transparent bg-transparent"
            : "border-line bg-surface/95 shadow-card backdrop-blur-xl backdrop-saturate-150",
        )}
      >
        <Link
          to="/"
          aria-label="Razor Trip home"
          className="rounded-full transition duration-150 hover:opacity-75"
        >
          <Wordmark />
        </Link>

        <nav aria-label="Account" className="flex items-center gap-1">
          <ThemeToggle />
          <HeaderWalletChip />
          <SessionNav />
        </nav>
      </div>
    </header>
  );
}

function SiteFooter(): ReactNode {
  const onLanding = useRouterState({ select: (state) => state.location.pathname === "/" });
  // Only the landing page has a footer; inside the app it would repeat the header.
  return onLanding ? <LandingFooter /> : null;
}
