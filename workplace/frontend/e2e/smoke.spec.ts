import { expect, test, type Page } from "@playwright/test";

// Open the app and wait for the mock worker before interacting.
async function openMockApp(page: Page, path = "/") {
  await page.goto(path);
  await expect(page.locator("html[data-msw-ready='true']")).toBeAttached({
    timeout: 30_000,
  });
  // exactly ONE main landmark app-wide (layout owns it)
  await expect(page.locator("main")).toHaveCount(1);
}

// M16.1 (check retirement): the app shell smoke — primary nav, the labeled guide
// entry, and the absence of any check surface. The verify UI specs left with the
// /check route; the backend engine stays frozen for a later iteration.

test("the shell: Today home, three primary destinations, no check entries", async ({ page }) => {
  await openMockApp(page);
  await expect(page.getByRole("heading", { name: "Today", level: 1 })).toBeVisible();

  const nav = page.getByLabel("Primary");
  await expect(nav.getByRole("link")).toHaveCount(3);
  await expect(nav.getByRole("link", { name: "Today" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Sources" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Knowledge" })).toBeVisible();

  // no link anywhere points at the retired routes
  for (const href of await page
    .locator("a[href]")
    .evaluateAll((as) => as.map((a) => a.getAttribute("href")))) {
    expect(href).not.toBe("/check");
    expect(href).not.toBe("/memory");
  }
});

test("the guide reopens from the labeled header button (M16.1: no cryptic ?)", async ({ page }) => {
  await openMockApp(page);
  const guide = page.getByRole("region", { name: "Welcome to daily" });
  await expect(guide).toBeVisible(); // first visit: the guide is open
  await guide.getByRole("button", { name: "Got it — take me to daily" }).click();
  await expect(guide).toHaveCount(0);

  const guideBtn = page.getByRole("button", { name: "Open the guide" });
  await expect(guideBtn).toHaveText("Guide");
  await guideBtn.click();
  await expect(page.getByRole("region", { name: "Welcome to daily" })).toBeVisible();
  // the guide's copy keeps the honest boundaries without check-era language
  // (.first(): the tracked-section note phrases the same boundary)
  await expect(page.getByText(/not in real time/).first()).toBeVisible();
});

test("the tracked briefing renders without horizontal overflow", async ({ page }) => {
  await openMockApp(page);
  await expect(page.getByRole("region", { name: "New from your sources" })).toBeVisible();
  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 1,
  );
  expect(noOverflow).toBe(true);
});

// 2026-07-10 (owner): Today is an AIHOT-style timeline with board filter tabs.
test("Today: date/poll header, chronological timeline, board tabs filter", async ({ page }) => {
  await openMockApp(page);
  const head = page.getByLabel("Today overview");
  // the LATEST poll across the mock sources + the honest non-real-time boundary
  await expect(head.getByText(/Last poll .*not real-time/)).toBeVisible();
  // the timeline: items under a day header, titles deep-link to the detail page
  await expect(
    page.getByRole("link", { name: "SEC statement on market-structure rulemaking" }),
  ).toBeVisible();
  await expect(page.getByText("Markets Daily — episode 214")).toBeVisible();
  // board tabs narrow the feed; All brings everything back
  const tabs = page.getByRole("group", { name: "Board filter" });
  await tabs.getByRole("button", { name: "经济" }).click();
  await expect(
    page.getByRole("link", { name: "SEC statement on market-structure rulemaking" }),
  ).toBeVisible();
  await expect(page.getByText("Markets Daily — episode 214")).toHaveCount(0);
  await tabs.getByRole("button", { name: "All" }).click();
  await expect(page.getByText("Markets Daily — episode 214")).toBeVisible();
  // no score / featured badge anywhere (owner: 都不要)
  await expect(page.locator("body")).not.toContainText(/精选|\/100|credibility|verdict/i);
});
