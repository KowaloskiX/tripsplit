import { expect, type Locator, type Page } from "@playwright/test";

export const PASSWORD = "correct-horse-battery-staple";

/** `true` skips everything that waits for the real booking agent (`pnpm test:e2e:fast`). */
export const FAST = process.env.E2E_FAST === "1";

/** A unique email per run — the database is not cleaned between runs. */
export function uniqueEmail(prefix = "e2e"): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/** An ISO date `days` from today — trips have to be in the future. */
export function isoInDays(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

/** Parses "1 234,56 zł" / "PLN 1,234.56" / "-12.00 PLN" into minor units. */
export function parseMoneyMinor(text: string): number {
  const cleaned = text.replace(/[^\d,.-]/g, "");
  const match = cleaned.match(/-?[\d.,]+/);
  if (!match) throw new Error(`no amount in "${text}"`);
  let digits = match[0];
  const lastSep = Math.max(digits.lastIndexOf(","), digits.lastIndexOf("."));
  let decimals = "00";
  if (lastSep !== -1 && digits.length - lastSep - 1 === 2) {
    decimals = digits.slice(lastSep + 1);
    digits = digits.slice(0, lastSep);
  }
  const whole = digits.replace(/[^\d-]/g, "");
  const sign = whole.startsWith("-") ? -1 : 1;
  return sign * (Math.abs(Number(whole || "0")) * 100 + Number(decimals));
}

export async function registerUser(page: Page, email = uniqueEmail()): Promise<string> {
  await page.goto("/register");
  await page.getByLabel("Organization").fill("TripSplit E2E");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/app$/);
  return email;
}

export type TripOptions = {
  title?: string;
  groupSize?: number;
  budget?: string;
};

/** Fills every field of the create-trip form and lands in the new room. Returns the trip id. */
export async function createTrip(page: Page, options: TripOptions = {}): Promise<string> {
  const { title = "Weekend in Prague", groupSize = 6, budget = "900" } = options;
  await page.goto("/app");
  await expect(page.getByRole("heading", { name: "Where to next?" })).toBeVisible();
  // The long form is the fallback to the one-sentence plan, folded by default.
  if (!(await page.getByLabel("Trip name").isVisible())) {
    await page.getByText("Set every detail yourself").click();
  }
  await page.getByLabel("Trip name").fill(title);
  await page
    .getByLabel("Brief for the agent")
    .fill("Weekend in Prague for the group, cheap, good food, one museum");
  await page.getByLabel("From").fill("Warszawa");
  await page.getByLabel("To", { exact: true }).fill("Praha");
  await page.getByLabel("Getting there").selectOption("rail");
  await page.getByLabel("Leave no earlier than").selectOption("7");
  await page.getByLabel("Changes").selectOption("1");
  await page.getByLabel("People").fill(String(groupSize));
  await page.getByLabel("Start").fill(isoInDays(30));
  await page.getByLabel("End").fill(isoInDays(32));
  await page.getByLabel("Budget per person (PLN)").fill(budget);
  await page.getByLabel("Your name").fill("Ola");
  await page.getByRole("button", { name: "Create trip" }).click();
  await expect(page).toHaveURL(/\/t\/[^/]+$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
  const tripId = page.url().split("/t/")[1];
  if (!tripId) throw new Error(`no trip id in ${page.url()}`);
  return tripId;
}

/** The dev-only demo controls: a `<details>` that has to be open to click its buttons. */
export async function demoControls(page: Page): Promise<Locator> {
  const details = page.locator("details", { hasText: "Demo controls (dev only)" });
  if (!(await details.evaluate((el) => (el as HTMLDetailsElement).open))) {
    await details.locator("summary").click();
  }
  return details;
}

/** Fills the signed-in member's own traveller details (needed before an agent books). */
/** "Pay my share" goes through the wallet: a fresh user tops up the shortfall by (dummy) BLIK
 * and the share is paid once the dummy bank confirms. */
export async function payMyShare(page: Page): Promise<void> {
  await page.getByRole("button", { name: /^Pay my share · / }).click();
  const sheet = page.getByRole("dialog", { name: "Pay my share" });
  await sheet.getByLabel("BLIK code").fill("123456");
  await sheet.getByRole("button", { name: /^Top up .* & pay$/ }).click();
  await sheet.getByRole("button", { name: "Done" }).click({ timeout: 15_000 });
  await expect(sheet).toHaveCount(0);
}

export async function fillMyTravellerDetails(page: Page, fullName: string): Promise<void> {
  const form = page.getByRole("form", { name: "Your traveller details" });
  if (!(await form.isVisible())) {
    // The room folds the whole section into one row until it is needed.
    const section = page.locator("details", {
      has: page.locator("summary", { hasText: "Traveller details" }),
    });
    if (
      (await section.count()) > 0 &&
      !(await section.first().evaluate((el) => (el as HTMLDetailsElement).open))
    ) {
      await section.first().locator("summary").first().click();
    }
  }
  if (!(await form.isVisible())) {
    // Collapsed before paying: "Add your travel details" (or "your travel details" once saved).
    await page.getByText(/your travel details$/i).click();
  }
  await form.getByLabel("Name on the document").fill(fullName);
  await form.getByLabel("Date of birth").fill("1994-05-17");
  await form.getByLabel("Nationality").fill("PL");
  await form.getByLabel("Passport / ID number").fill("AB1234567");
  await form.getByLabel("Document expiry").fill(isoInDays(900));
  await form.getByLabel("Gender").selectOption("female");
  await form.getByRole("button", { name: "Save my details" }).click();
  await expect(form.getByText("Saved.")).toBeVisible();
}

export async function seedGroup(page: Page, groupSize: number): Promise<void> {
  const controls = await demoControls(page);
  await controls.getByRole("button", { name: `Seed ${groupSize - 1} members` }).click();
  await expect(page.getByText(`${groupSize}/${groupSize} people`)).toBeVisible();
}

export async function generatePackages(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Generate packages" }).click();
  await expect(page.getByText("Vote for a package")).toBeVisible({ timeout: 60_000 });
}

/** I vote for the first package, everyone else follows, the organizer closes the vote. */
export async function voteAndClose(page: Page, groupSize: number): Promise<void> {
  const votes = page.getByRole("button", { name: "Vote", exact: true });
  await expect(votes.first()).toBeVisible();
  await votes.first().click();
  await expect(page.getByRole("button", { name: "Your vote" })).toBeVisible();
  await (await demoControls(page)).getByRole("button", { name: /Everyone votes/ }).click();
  await expect(page.getByText(`${groupSize} votes`, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Close voting" }).click();
  await expect(page.getByText("Shares", { exact: true })).toBeVisible({ timeout: 30_000 });
}

/** A fresh trip from "collecting" to "paying". */
export async function driveToPaying(page: Page, groupSize = 6): Promise<void> {
  await seedGroup(page, groupSize);
  await generatePackages(page);
  await voteAndClose(page, groupSize);
}

/** The real agent drives the demo rail site; a run takes from seconds to a couple of minutes. */
export const AGENT_TIMEOUT = 240_000;

/**
 * Starts every startable booking and approves every summary until the trip is booked. Agent
 * purchases stop at the supplier's summary ("Needs approval"); direct API purchases ask for
 * approval without an agent.
 */
export async function bookEverything(
  page: Page,
  onFirstApproval?: () => Promise<void>,
): Promise<void> {
  let beforeApproval = onFirstApproval;
  const deadline = Date.now() + AGENT_TIMEOUT * 2;
  while (Date.now() < deadline) {
    const failed = page.getByText(/^The agent could not finish:/).first();
    if (await failed.isVisible()) throw new Error(`booking failed: ${await failed.innerText()}`);
    const approve = page.getByRole("button", { name: "Approve and pay" }).first();
    if (await approve.isVisible()) {
      await beforeApproval?.();
      beforeApproval = undefined;
      await approve.click();
      await page.waitForTimeout(1_000);
      continue;
    }
    const start = page.getByRole("button", { name: /^(Start booking|Book everything)$/ }).first();
    if ((await start.isVisible()) && (await start.isEnabled())) {
      await start.click();
      await page.waitForTimeout(1_000);
      continue;
    }
    if (await page.getByText("Everything booked").isVisible()) return;
    await page.waitForTimeout(2_000);
  }
  throw new Error("the bookings did not all confirm in time");
}
