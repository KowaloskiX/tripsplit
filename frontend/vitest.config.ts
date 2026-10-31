import { fileURLToPath } from "node:url";
import viteReact from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * A config separate from `vite.config.ts` — the TanStack Start plugin takes over the
 * application build and is not needed for component tests.
 */
export default defineConfig({
  plugins: [viteReact()],
  resolve: {
    // `fileURLToPath`, not `.pathname`: a space in a parent directory stays percent-encoded in
    // the latter and every alias then points at a path that does not exist.
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // The test harness (MSW, router render) lives in tests/; the tests themselves sit next
      // to the code.
      "@tests": fileURLToPath(new URL("./tests", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["src/**/*.test.tsx", "src/**/*.test.ts"],
  },
});
