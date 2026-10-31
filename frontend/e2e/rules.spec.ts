import { type BrowserContext, expect, type Page, test } from "@playwright/test";

import { createTrip, demoControls, driveToPaying, parseMoneyMinor, registerUser } from "./helpers";

// Three users register (argon2 on purpose is slow) and the rooms poll: on a busy machine the
// default 30 s is too tight.
test.describe.configure({ timeout: 90_000 });

/** The double-submit CSRF header the app's own client sends on every mutation. */
async function csrfHeader(context: BrowserContext): Promise<Record<string, string>> {
  const cookies = await context.cookies();
  const token = cookies.find((cookie) => cookie.name.endsWith("csrf_token"))?.value ?? "";
  return { "X-CSRF-Token": token };
}

/** The invite URL exactly as the room shows it. */
async function inviteUrl(page: Page): Promise<string> {
  const url = await page.locator("code", { hasText: "/join/" }).innerText();
  return new URL(url).pathname;
}

test("a booking cannot start while a share is unpaid, and the UI says why", async ({
  page,
  context,
}) => {
  await registerUser(page);
  const tripId = await createTrip(page, { title: "Unpaid shares", groupSize: 3 });
  await driveToPaying(page, 3);

  await page.getByRole("button", { name: /^Pay my share · / }).click();
  await expect(page.getByText("1/3 paid")).toBeVisible();
  await expect(
    page.getByText("Your share is paid. The agent books as soon as everyone else has paid too."),
  ).toBeVisible();

  await page.goto(`/t/${tripId}/bookings`);
  await expect(page.getByText("Waiting for everyone to pay")).toBeVisible();
  await expect(page.getByText("Not started").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /^(Start booking|Book everything)$/ })).toHaveCount(
    0,
  );

  // The server enforces the same rule: a hand-made start is refused.
  const listing = await page.request.get(`/api/trips/${tripId}/bookings`);
  const bookingId = (await listing.json()).bookings[0].id as string;
  const start = await page.request.post(`/api/trips/${tripId}/bookings/${bookingId}/start`, {
    headers: await csrfHeader(context),
  });
  expect(start.status()).toBe(409);
  expect((await start.json()).code).toBe("trip_not_ready");
});

test("a member leaves; afterwards the room is a 404 for them and for strangers", async ({
  page,
  browser,
}) => {
  await registerUser(page);
  const tripId = await createTrip(page, { title: "Leaving early", groupSize: 4 });
  const invite = await inviteUrl(page);

  const friendContext = await browser.newContext();
  const friend = await friendContext.newPage();
  await registerUser(friend);
  await friend.goto(invite);
  await expect(friend.getByRole("heading", { name: "You are invited on a trip" })).toBeVisible();
  await friend.getByLabel("Your name").fill("Bartek");
  await friend.getByRole("button", { name: "Join the trip" }).click();
  await expect(friend).toHaveURL(new RegExp(`/t/${tripId}$`));
  await expect(friend.getByText("2/4 people")).toBeVisible();

  await friend.getByRole("button", { name: "Leave trip" }).click();
  await expect(friend.getByText("Leave? The rest of the group re-split the cost.")).toBeVisible();
  await friend.getByRole("button", { name: "Yes, leave" }).click();
  await expect(friend).toHaveURL(/\/app$/);

  await friend.goto(`/t/${tripId}`);
  await expect(friend.getByRole("heading", { name: "No such trip" })).toBeVisible();
  await friendContext.close();

  await page.reload();
  await expect(page.getByText("1/4 people")).toBeVisible();
  // The organizer cannot leave their own trip.
  await expect(page.getByRole("button", { name: "Leave trip" })).toHaveCount(0);

  const strangerContext = await browser.newContext();
  const stranger = await strangerContext.newPage();
  await registerUser(stranger);
  await stranger.goto(`/t/${tripId}`);
  await expect(stranger.getByRole("heading", { name: "No such trip" })).toBeVisible();
  const api = await stranger.request.get(`/api/trips/${tripId}`);
  expect(api.status()).toBe(404);
  await strangerContext.close();
});

test("a member who paid and drops out is refunded and the rest re-split", async ({ page }) => {
  await registerUser(page);
  await createTrip(page, { title: "Drop-out re-split", groupSize: 4 });
  await driveToPaying(page, 4);
  const totalBefore = await page
    .getByText(/ total$/)
    .first()
    .innerText();

  await (await demoControls(page)).getByRole("button", { name: "Everyone else pays" }).click();
  await expect(page.getByText("3/4 paid")).toBeVisible();
  await (await demoControls(page)).getByRole("button", { name: / drops out$/ }).click();

  // Three shares left, each bigger than what was paid, so nobody counts as paid any more; the
  // leaver keeps a settled zero share with a refund badge.
  await expect(page.getByText(/^refund /)).toBeVisible();
  await expect(page.getByText(/^0\/3 paid$/)).toBeVisible();
  await expect(page.getByText(/^New share: .+ each \(\+.+\)\. Please top up/)).toBeVisible();
  await expect(page.getByText(/ total$/).first()).toHaveText(totalBefore);
  const total = parseMoneyMinor(totalBefore);
  const shares = page.locator("table tbody tr td:nth-child(2)");
  await expect(shares).toHaveCount(4);
  const amounts = (await shares.allInnerTexts()).map(parseMoneyMinor);
  expect(amounts.filter((amount) => amount > 0)).toHaveLength(3);
  expect(amounts.reduce((sum, amount) => sum + amount, 0)).toBe(total);
});
