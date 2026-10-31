import { fileURLToPath } from "node:url";

import { expect, type Page, test } from "@playwright/test";

import {
  bookEverything,
  createTrip,
  demoControls,
  FAST,
  fillMyTravellerDetails,
  generatePackages,
  registerUser,
  seedGroup,
  voteAndClose,
} from "./helpers";

/**
 * Full-page screenshots for a human (or an agent) to look at — not pixel assertions. They land
 * in `e2e/__screens__/` (gitignored). The one hard check: no page scrolls sideways.
 */
const SCREENS_DIR = fileURLToPath(new URL("./__screens__/", import.meta.url));
const VIEWPORTS = [
  { name: "mobile", width: 390, height: 844 },
  { name: "desktop", width: 1440, height: 900 },
] as const;

async function shoot(page: Page, name: string): Promise<void> {
  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    // Let layout, fonts and entrance animations settle.
    await page.evaluate(() => document.fonts.ready);
    // A full-page capture of a scrolled page paints the sticky header mid-page.
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(700);
    await page.screenshot({
      path: `${SCREENS_DIR}${name}-${viewport.name}.png`,
      fullPage: true,
      animations: "disabled",
    });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect.soft(overflow, `${name} at ${viewport.name} scrolls sideways`).toBeLessThanOrEqual(0);
  }
}

test("screenshots of every stage at phone and desktop sizes", async ({ page }) => {
  test.setTimeout(FAST ? 180_000 : 600_000);

  await page.goto("/", { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { level: 1 })).toContainText("From group");
  await shoot(page, "01-landing");

  await registerUser(page);
  await shoot(page, "02-app");

  const tripId = await createTrip(page, { title: "Weekend in Prague" });
  await fillMyTravellerDetails(page, "Ola Organizer");
  await seedGroup(page, 6);
  await shoot(page, "03-room-collecting");

  await generatePackages(page);
  await shoot(page, "04-room-voting");

  await voteAndClose(page, 6);
  await shoot(page, "05-room-paying");

  await page.getByRole("button", { name: /^Pay my share · / }).click();
  await (await demoControls(page)).getByRole("button", { name: "Everyone else pays" }).click();
  await expect(page.getByText("6/6 paid")).toBeVisible();
  await shoot(page, "06-room-booking");

  await page.goto(`/t/${tripId}/bookings`);
  await expect(page.getByRole("heading", { name: "Bookings", level: 1 })).toBeVisible();
  await shoot(page, "07-bookings-ready");
  if (FAST) return;

  await bookEverything(page, () => shoot(page, "08-bookings-awaiting-approval"));
  await expect(page.getByText("Everything booked")).toBeVisible({ timeout: 30_000 });
  await shoot(page, "09-bookings-booked");

  await page.getByRole("button", { name: "Simulate disruption" }).click();
  await expect(page.getByText(/^Replaced \d+ purchases?\./)).toBeVisible({ timeout: 30_000 });
  await shoot(page, "10-bookings-disrupted");

  await page.goto(`/t/${tripId}`);
  await expect(page.getByText(/paid$/).first()).toBeVisible();
  await shoot(page, "11-room-after-disruption");
});
