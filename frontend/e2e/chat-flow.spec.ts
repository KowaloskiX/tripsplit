import { expect, type Page, test } from "@playwright/test";

import { isoInDays, registerUser } from "./helpers";

/**
 * The chat flow at /plan on simulated suppliers: one sentence, the live search, transport
 * and stay picked one at a time, activities skipped, "I'll pay for everyone" with BLIK,
 * the basket approved and the tickets shown — all in one thread. The brief asks for a
 * flight: `sim_flight` is an API supplier, so no browser agent is involved.
 */

// Optional screenshots of every step: CHAT_SHOTS_DIR=/tmp/x CHAT_VIEWPORT=390x844.
const SHOTS = process.env.CHAT_SHOTS_DIR;
const [WIDTH, HEIGHT] = (process.env.CHAT_VIEWPORT ?? "1440x900").split("x").map(Number);
const SETTLE_MS = 900;

async function shot(page: Page, name: string): Promise<void> {
  if (!SHOTS) return;
  await page.waitForTimeout(SETTLE_MS); // entry animations and the smooth scroll settle
  await page.screenshot({ path: `${SHOTS}/${WIDTH}x${HEIGHT}-${name}.png` });
}

test.use({ viewport: { width: WIDTH ?? 1440, height: HEIGHT ?? 900 } });

test.describe("the trip as one chat", () => {
  test.setTimeout(180_000);

  test("brief -> transport -> stay -> skip -> pay for everyone -> approve -> tickets", async ({
    page,
  }) => {
    await registerUser(page);
    await page.goto("/plan");
    await expect(page.getByRole("heading", { name: "Where are we going?" })).toBeVisible();
    await shot(page, "01-brief");

    const brief = `Weekend in Prague from Warsaw for 2, ${isoInDays(30)}–${isoInDays(32)}, up to 2000 zł each, by plane`;
    await page.getByLabel("Message").fill(brief);
    await page.getByRole("button", { name: "Send" }).click();

    // Step 1: what the agent understood, as chips.
    const understood = page.getByRole("region", { name: "Brief" });
    await expect(understood.getByText("People")).toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveURL(/\/plan\?trip=/);

    // Steps 2-3: suppliers ticked off, then the ways to get there.
    const transport = page.getByRole("region", { name: "How do you want to get there?" });
    await expect(transport).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("region", { name: "Search" }).getByText(/✓/).first()).toBeVisible();
    await shot(page, "03-transport");
    await transport.getByRole("button", { name: "Pick" }).first().click();

    // Step 4: where to stay.
    const stay = page.getByRole("region", { name: "Where do you want to stay?" });
    await expect(stay).toBeVisible();
    await shot(page, "04-stay");
    await stay.getByRole("button", { name: "Stay here" }).first().click();

    // Step 5: activities — skipped.
    const activities = page.getByRole("region", { name: "Anything to do while you're there?" });
    await expect(activities).toBeVisible();
    await shot(page, "05-activities");
    await activities.getByRole("button", { name: "Skip" }).click();
    await expect(page.getByText("Nothing for now, thanks")).toBeVisible();

    // Step 6: the summary locks it in.
    const summary = page.getByRole("region", { name: "Summary" });
    await expect(summary.getByText("per person").first()).toBeVisible();
    await shot(page, "06-summary");
    await summary.getByRole("button", { name: "Looks good" }).click();

    // An airline needs every passenger's document details before it can be booked.
    const details = page.getByRole("region", { name: "Your details" });
    await expect(details).toBeVisible({ timeout: 15_000 });
    await shot(page, "07a-details");
    await details.getByLabel("Name on the document").fill("Ola Organizer");
    await details.getByLabel("Date of birth").fill("1990-05-17");
    await details.getByLabel("Nationality").fill("PL");
    await details.getByLabel("Passport / ID number").fill("EH1234567");
    await details.getByLabel("Document expiry").fill(isoInDays(2000));
    await details.getByLabel("Gender").selectOption("female");
    await details.getByRole("button", { name: "Save my details" }).click();
    await expect(details).toBeHidden({ timeout: 10_000 });

    // Step 7: who pays — the organizer covers everyone with BLIK.
    const who = page.getByRole("region", { name: "Who pays" });
    await expect(who).toBeVisible({ timeout: 15_000 });
    await shot(page, "07b-who");
    await who.getByRole("button", { name: /I'll pay for everyone/ }).click();
    // A first payment above the KYC-light limit asks for a quick ID check first.
    const verify = who.getByRole("button", { name: "Verify my ID" });
    if (await verify.isVisible()) {
      await shot(page, "07c-kyc");
      await who.getByLabel("Full name").fill("Ola Organizer");
      await who.getByLabel("Date of birth").fill("1990-05-17");
      await verify.click();
    }
    const pay = page.getByRole("region", { name: "Pay for everyone" });
    await expect(pay).toBeVisible({ timeout: 15_000 });
    await pay.getByLabel(/BLIK code/i).fill("123456");
    await shot(page, "07d-pay");
    await pay.getByRole("button", { name: /^Pay / }).click();

    // Step 8: the agent books; the organizer approves the basket; tickets.
    const approve = page.getByRole("button", { name: /Approve basket \(total/ });
    await expect(approve).toBeVisible({ timeout: 60_000 });
    await shot(page, "08-approve");
    await approve.click();
    const tickets = page.getByRole("region", { name: "Tickets" });
    await expect(tickets.getByText(/Done — all \d+ booked/)).toBeVisible({ timeout: 60_000 });
    await expect(tickets.getByRole("listitem").first()).toContainText("booking ref");
    await shot(page, "09-tickets");
  });
});
