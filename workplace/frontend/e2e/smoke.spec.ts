import { expect, test, type Page } from "@playwright/test";

// Open the app and wait for the mock worker before interacting.
async function openMockApp(page: Page, path = "/") {
  // returning-user flag: the first-visit welcome redirect has its own spec
  await page.addInitScript(() => window.localStorage.setItem("daily.onboarded", "1"));
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

test("the shell: Today home, four primary destinations, no check entries", async ({ page }) => {
  await openMockApp(page);
  await expect(page.getByRole("heading", { name: "Today", level: 1 })).toBeVisible();

  const nav = page.getByLabel("Primary");
  await expect(nav.getByRole("link")).toHaveCount(4);
  await expect(nav.getByRole("link", { name: "Today" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Sources" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Knowledge" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Settings" })).toBeVisible();

  // no link anywhere points at the retired routes
  for (const href of await page
    .locator("a[href]")
    .evaluateAll((as) => as.map((a) => a.getAttribute("href")))) {
    expect(href).not.toBe("/check");
    expect(href).not.toBe("/memory");
  }
});

test("the guide lives on the welcome page; the labeled header entry links there", async ({
  page,
}) => {
  await openMockApp(page);
  const guideLink = page.getByRole("link", { name: "Open the guide" });
  await expect(guideLink).toHaveText("Guide");
  await expect(guideLink).toHaveAttribute("href", "/welcome");
});

test("the tracked briefing renders without horizontal overflow", async ({ page }) => {
  await openMockApp(page);
  await expect(page.getByRole("region", { name: "New from your sources" })).toBeVisible();
  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 1,
  );
  expect(noOverflow).toBe(true);
});

// Today is an AIHOT-style timeline with board filter tabs.
test("Today: date/poll header, chronological timeline, board tabs filter", async ({ page }) => {
  await openMockApp(page);
  const head = page.getByLabel("Today overview");
  // the LATEST poll across the mock sources + the honest non-real-time boundary
  await expect(head.getByText(/Last poll .*not real-time/)).toBeVisible();
  // the timeline: items under a day header, titles deep-link to the detail page
  await expect(
    page.getByRole("link", { name: "SEC statement on market-structure rulemaking" }),
  ).toBeVisible();
  // undated items live in the collapsed section — expand to read them
  await page.getByText(/No publish date/).click();
  await expect(page.getByText("Markets Daily — episode 214")).toBeVisible();
  // board tabs narrow the feed; All brings everything back
  const tabs = page.getByRole("group", { name: "Board filter" });
  await tabs.getByRole("button", { name: "经济" }).click();
  await expect(
    page.getByRole("link", { name: "SEC statement on market-structure rulemaking" }),
  ).toBeVisible();
  await expect(page.getByText("Markets Daily — episode 214")).toHaveCount(0);
  await tabs.getByRole("button", { name: "All" }).click();
  await page.getByText(/No publish date/).click();
  await expect(page.getByText("Markets Daily — episode 214")).toBeVisible();
  // no score / featured badge anywhere (deliberately none)
  await expect(page.locator("body")).not.toContainText(/精选|\/100|credibility|verdict/i);
});
