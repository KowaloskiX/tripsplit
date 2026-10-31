import { expect, type Page, test } from "@playwright/test";

import { isoInDays, registerUser } from "./helpers";

/**
 * The demo's golden path at /plan, on simulated suppliers: one sentence, the live search, a
 * transport card, a stay card, activities skipped, the summary, traveller details, "I'll pay
 * for everyone" with BLIK (and the KYC-light check), the basket approved, tickets with booking
 * refs — all in one thread, from a fresh trip.
 *
 * - train: the booking agent buys the train on the demo rail site (rules/replay, no LLM);
 * - flight: `sim_flight` is an API supplier, booked directly at the approval.
 *
 * Both work with AUTO_BOOK on (the demo) or off (Playwright's own backend): "Book everything"
 * is clicked when it is offered. Optional artifacts: CHAT_SHOTS_DIR=/tmp/x saves a 1440×900
 * screenshot of every step; CHAT_VIDEO_DIR=/tmp/x records a video.
 */

const SHOTS = process.env.CHAT_SHOTS_DIR;
const [WIDTH, HEIGHT] = (process.env.CHAT_VIEWPORT ?? "1440x900").split("x").map(Number);
const SIZE = { width: WIDTH ?? 1440, height: HEIGHT ?? 900 };
const SETTLE_MS = 900;

test.use({
  viewport: SIZE,
  video: process.env.CHAT_VIDEO_DIR ? { mode: "on", size: SIZE } : "off",
});

type GoldenCase = {
  name: string;
  brief: string;
  people: number;
  /** Only an airline asks for documents; a train needs names only. */
  documents: boolean;
};

const TRAIN: GoldenCase = {
  name: "train",
  brief: `Weekend in Prague for 4, ${isoInDays(20)}–${isoInDays(22)}, under 900 zł each, by train`,
  people: 4,
  documents: false,
};

const FLIGHT: GoldenCase = {
  name: "flight",
  brief: `Weekend in Barcelona for 2, ${isoInDays(13)}–${isoInDays(15)}, by plane`,
  people: 2,
  documents: true,
};

async function shot(page: Page, name: string): Promise<void> {
  if (!SHOTS) return;
  await page.waitForTimeout(SETTLE_MS); // entry animations and the smooth scroll settle
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

async function goldenPath(page: Page, golden: GoldenCase): Promise<void> {
  const step = (name: string) => shot(page, `${golden.name}-${name}`);
  await registerUser(page);
  await page.goto("/plan");
  await expect(page.getByRole("heading", { name: "Where are we going?" })).toBeVisible();
  await step("01-brief");

  await page.getByLabel("Message").fill(golden.brief);
  await page.getByRole("button", { name: "Send" }).click();

  // What the agent understood, as chips.
  const understood = page.getByRole("region", { name: "Brief" });
  await expect(understood.getByText("People")).toBeVisible({ timeout: 15_000 });
  await expect(understood.getByText(String(golden.people), { exact: true }).first()).toBeVisible();
  await expect(page).toHaveURL(/\/plan\?trip=/);
  await step("02-understood");

  // Suppliers ticked off, then the ways to get there.
  const transport = page.getByRole("region", { name: "How do you want to get there?" });
  await expect(transport).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("region", { name: "Search" }).getByText(/✓/).first()).toBeVisible();
  await step("03-transport");
  await transport.getByRole("button", { name: "Pick" }).first().click();

  const stay = page.getByRole("region", { name: "Where do you want to stay?" });
  await expect(stay).toBeVisible();
  await step("04-stay");
  await stay.getByRole("button", { name: "Stay here" }).first().click();

  const activities = page.getByRole("region", { name: "Anything to do while you're there?" });
  await expect(activities).toBeVisible();
  await step("05-activities");
  await activities.getByRole("button", { name: "Skip" }).click();
  await expect(page.getByText("Nothing for now, thanks")).toBeVisible();

  const summary = page.getByRole("region", { name: "Summary" });
  await expect(summary.getByText(`Total for ${golden.people} people`)).toBeVisible();
  await step("06-summary");
  await summary.getByRole("button", { name: "Looks good" }).click();

  // A fresh account has no traveller details yet.
  const details = page.getByRole("region", { name: "Your details" });
  await expect(details).toBeVisible({ timeout: 15_000 });
  await step("07a-details");
  await details.getByLabel("Name on the document").fill("Ola Organizer");
  if (golden.documents) {
    await details.getByLabel("Date of birth").fill("1990-05-17");
    await details.getByLabel("Nationality").fill("PL");
    await details.getByLabel("Passport / ID number").fill("EH1234567");
    await details.getByLabel("Document expiry").fill(isoInDays(2000));
    await details.getByLabel("Gender").selectOption("female");
  }
  await details.getByRole("button", { name: "Save my details" }).click();
  await expect(details).toBeHidden({ timeout: 10_000 });

  // Who pays: the organizer covers everyone with BLIK.
  const who = page.getByRole("region", { name: "Who pays" });
  await expect(who).toBeVisible({ timeout: 15_000 });
  await step("07b-who");
  await who.getByRole("button", { name: /I'll pay for everyone/ }).click();
  // A first payment above the KYC-light limit asks for a quick ID check first.
  const pay = page.getByRole("region", { name: "Pay for everyone" });
  const verify = who.getByRole("button", { name: "Verify my ID" });
  await expect(pay.or(verify).first()).toBeVisible({ timeout: 15_000 });
  if (await verify.isVisible()) {
    await step("07c-kyc");
    await who.getByLabel("Full name").fill("Ola Organizer");
    await who.getByLabel("Date of birth").fill("1990-05-17");
    await verify.click();
  }
  await expect(pay).toBeVisible({ timeout: 15_000 });
  await pay.getByLabel(/BLIK code/i).fill("123456");
  await step("07d-pay");
  await pay.getByRole("button", { name: /^Pay / }).click();

  // The agent books (AUTO_BOOK, or one click); the organizer approves the basket once.
  const approve = page.getByRole("button", { name: /Approve basket \(total/ });
  const bookAll = page.getByRole("button", { name: "Book everything" });
  await expect(approve.or(bookAll).first()).toBeVisible({ timeout: 30_000 });
  if (await bookAll.isVisible()) await bookAll.click();
  await expect(approve).toBeVisible({ timeout: 75_000 });
  await step("08-approve");
  await approve.click();

  const tickets = page.getByRole("region", { name: "Tickets" });
  await expect(tickets.getByText(/Done — all \d+ booked/)).toBeVisible({ timeout: 45_000 });
  const refs = tickets.getByRole("listitem");
  await expect(refs.first()).toContainText("booking ref");
  for (const ticket of await refs.all()) {
    await expect(ticket).not.toContainText(/booking ref\s*confirmed$/i); // a real ref each
  }
  await expect(page.getByText(/couldn't|could not|went wrong/i)).toHaveCount(0);
  await step("09-tickets");
}

test.describe("the trip as one chat", () => {
  test.setTimeout(180_000);

  test("train: brief -> train -> stay -> skip -> pay for everyone -> agent books -> tickets", async ({
    page,
  }) => {
    await goldenPath(page, TRAIN);
  });

  test("flight: brief -> flight -> stay -> skip -> pay for everyone -> approve -> tickets", async ({
    page,
  }) => {
    await goldenPath(page, FLIGHT);
  });
});
