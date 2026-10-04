import { expect, test, type Page } from "@playwright/test";

// The welcome page: one continuous scroll — what daily is, the guide, and the
// honest boundaries. First visit lands here; "Enter daily" opens the app.

async function openWelcome(page: Page) {
  await page.addInitScript(() => window.localStorage.setItem("daily.onboarded", "1"));
  await page.goto("/welcome");
  await expect(page.locator("html[data-msw-ready='true']")).toBeAttached({ timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // the intro tween moves the hero for ~1s; let it settle before interacting
  await page.waitForTimeout(1400);
}

test("a first visit to the app lands on the welcome page", async ({ page }) => {
  await page.goto("/"); // no returning-user flag set
  await page.waitForURL("**/welcome");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Everything you follow");
});

test("all three movements are on one page, boundaries included", async ({ page }) => {
  await openWelcome(page);
  // movement 2: the guide steps (the old onboarding panel's content)
  const guide = page.getByText("Add your sources");
  await guide.scrollIntoViewIfNeeded();
  await expect(guide).toBeVisible();
  await expect(page.getByText("Ask your knowledge")).toBeVisible();
  // movement 3: honesty stays first-class marketing copy
  const limits = page.getByText("Polling, not real-time");
  await limits.scrollIntoViewIfNeeded();
  await expect(limits).toBeVisible();
  await expect(page.getByText("Restating, not judging")).toBeVisible();
  // never any check-era language, and no horizontal overflow on any viewport
  await expect(page.locator("body")).not.toContainText(/credibility|verdict|\/100|deep check/i);
  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 1,
  );
  expect(noOverflow).toBe(true);
});

test("Enter daily marks the visit and opens Today", async ({ page }) => {
  await openWelcome(page);
  // the hero's own CTA (exact name — the header link carries an arrow)
  await page.getByRole("button", { name: "Enter daily", exact: true }).first().click();
  await page.waitForURL((url) => new URL(url).pathname === "/");
  await expect(page.getByRole("heading", { name: "Today", level: 1 })).toBeVisible();
  expect(await page.evaluate(() => window.localStorage.getItem("daily.onboarded"))).toBe("1");
});
