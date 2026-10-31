import { defineConfig, devices } from "@playwright/test";

// Configurable ports: on a developer machine 3000/8000 can be taken by another project.
// vite.config.ts reads the same variables, so the /api proxy points at the right backend.
const WEB_PORT = process.env.WEB_PORT ?? "3000";
const API_PORT = process.env.API_PORT ?? "8000";
const WEB_URL = `http://localhost:${WEB_PORT}`;
const API_URL = `http://localhost:${API_PORT}`;

/**
 * E2E over the money path: auth, a whole group trip (vote -> pay -> book -> approve ->
 * disruption), the booking rules and full-page screenshots.
 *
 * Requires the database: run `docker compose up -d` first. When Playwright starts the backend
 * itself it pins a deterministic setup: simulated stay/activity, the demo rail site driven by
 * the real agent (DEMO_SUPPLIER_URL = this backend), the catalogue researcher and a separate
 * database. A backend you started yourself is reused as is — start it with the same variables.
 * `E2E_FAST=1` (`pnpm test:e2e:fast`) skips the steps that wait for the real booking agent.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: WEB_URL,
    trace: "retain-on-failure",
    locale: "en-US",
    timezoneId: "Europe/Warsaw",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // No separate migration step: on dev the application creates indexes at startup.
      command: `uv run uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../backend",
      url: `${API_URL}/api/health`,
      env: {
        // sim_flight: an API supplier, so `chat-flow.spec.ts` books without the browser agent.
        SUPPLIERS: "demo_rail,sim_flight,sim_stay,sim_activity",
        DEMO_SUPPLIER_URL: API_URL,
        RESEARCHER: "catalog",
        MONGODB_DATABASE: process.env.E2E_MONGODB_DATABASE ?? "app_e2e",
        CORS_ORIGINS: WEB_URL,
        // Every test registers a fresh user, far beyond the production login limit. Counters
        // stay in process memory: a shared Redis bucket would also count other local backends.
        LOGIN_RATE_LIMIT: "1000/minute",
        // The specs click "Start booking" themselves; a dev .env may switch AUTO_BOOK on.
        AUTO_BOOK: "false",
        GLOBAL_RATE_LIMIT: "10000/minute",
        RATE_LIMIT_STORAGE_URL: "",
      },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "pnpm dev",
      url: WEB_URL,
      env: { WEB_PORT, API_PORT },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
