import { expect, type Page, test } from "@playwright/test";

import {
  AGENT_TIMEOUT,
  bookEverything,
  createTrip,
  demoControls,
  driveToPaying,
  FAST,
  fillMyTravellerDetails,
  parseMoneyMinor,
  registerUser,
} from "./helpers";

const GROUP = 6;

/** Every share in the table, in minor units, plus the panel's own total. */
async function readShares(page: Page): Promise<{ shares: number[]; total: number }> {
  const header = page.getByText(/ total$/).first();
  const total = parseMoneyMinor(await header.innerText());
  const rows = page.locator("table tbody tr");
  await expect(rows).toHaveCount(GROUP);
  const shares: number[] = [];
  for (const row of await rows.all()) {
    shares.push(parseMoneyMinor(await row.locator("td").nth(1).innerText()));
  }
  return { shares, total };
}

test.describe("a group trip from chat to tickets", () => {
  test.setTimeout(FAST ? 120_000 : AGENT_TIMEOUT * 2 + 120_000);

  test("register, decide, pay, book, approve, disrupt, re-split", async ({ page }) => {
    await registerUser(page);
    const tripId = await createTrip(page, { groupSize: GROUP });
    await expect(page.getByText("from Warszawa")).toBeVisible();
    await expect(page.getByText(`1/${GROUP} people`)).toBeVisible();

    await fillMyTravellerDetails(page, "Ola Organizer");
    await driveToPaying(page, GROUP);

    // The chosen package survives; its price is split into one share per member.
    await expect(page.getByText("chosen")).toBeVisible();
    const { shares, total } = await readShares(page);
    expect(shares.reduce((sum, share) => sum + share, 0)).toBe(total);
    expect(Math.max(...shares) - Math.min(...shares)).toBeLessThanOrEqual(1);
    await expect(page.getByText(`0/${GROUP} paid`)).toBeVisible();

    // While a share is unpaid nothing can be started.
    await expect(page.getByRole("button", { name: "Start booking" })).toHaveCount(0);

    await page.getByRole("button", { name: /^Pay my share · / }).click();
    await expect(page.getByText(`1/${GROUP} paid`)).toBeVisible();
    await (await demoControls(page)).getByRole("button", { name: "Everyone else pays" }).click();
    await expect(page.getByText(`${GROUP}/${GROUP} paid`)).toBeVisible();
    await expect(
      page.getByText("Everyone paid — the organizer can start the bookings"),
    ).toBeVisible();

    await page.goto(`/t/${tripId}/bookings`);
    await expect(page.getByRole("heading", { name: "Bookings", level: 1 })).toBeVisible();
    await expect(page.getByText("Booking", { exact: true })).toBeVisible();
    const bookingsTotal = parseMoneyMinor(await page.getByText(/^total /).innerText());
    expect(bookingsTotal).toBe(total);

    if (FAST) {
      await expect(page.getByRole("button", { name: "Start booking" }).first()).toBeEnabled();
      return;
    }

    await bookEverything(page);
    await expect(page.getByText("Everything booked")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/^Confirmed( · booking number .+)?$/).first()).toBeVisible();

    // The train is delayed: the agent's purchases are replaced and the shares re-split.
    await page.getByRole("button", { name: "Simulate disruption" }).click();
    const result = page.getByText(/^Replaced \d+ purchases?\. Rebooking: new total/);
    await expect(result).toBeVisible({ timeout: 30_000 });
    const newTotal = parseMoneyMinor(
      (await result.innerText()).replace(/^.*new total/, "").replace(/\(.*$/, ""),
    );
    const resplit = page.locator("li").filter({ hasText: /\) · / });
    await expect(resplit).toHaveCount(GROUP);
    let sum = 0;
    for (const row of await resplit.all()) {
      const text = await row.locator("span").nth(1).innerText();
      sum += parseMoneyMinor(text.split("(")[0] ?? "");
    }
    expect(sum).toBe(newTotal);
    await expect(
      page.getByText(/^(Disrupted|Rebooking|Waiting for everyone to pay|Booking)$/),
    ).toBeVisible();
  });
});
