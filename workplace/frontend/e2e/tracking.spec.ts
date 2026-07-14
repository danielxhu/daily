import { expect, test, type Page } from "@playwright/test";

// Open a page and wait for the mock worker before interacting.
async function openMockApp(page: Page, path = "/") {
  await page.goto(path);
  await expect(page.locator("html[data-msw-ready='true']")).toBeAttached({
    timeout: 30_000,
  });
}

// Reach tracking via the nav so MSW is ready before TrackingView mounts and fetches.
async function openTracking(page: Page) {
  await openMockApp(page);
  // scope to the primary nav — Today can also render a content "Sources" link
  await page.getByLabel("Primary").getByRole("link", { name: "Sources" }).click();
  await expect(page.getByRole("heading", { name: "Sources", level: 1 })).toBeVisible();
}

test("manage subscriptions: honesty banner, health, add", async ({ page }) => {
  await openTracking(page);

  // NFR-6 honesty disclosure
  await expect(page.getByText(/not real-time push/)).toBeVisible();

  const list = page.getByRole("list", { name: "Your sources" });
  await expect(
    list.getByText("https://www.federalreserve.gov/feeds/press_all.xml"),
  ).toBeVisible();
  await expect(list.getByText("unhealthy")).toBeVisible();
  // §6.6: the user sees a next step, not just a log line
  await expect(list.getByText(/Replace or remove this source/)).toBeVisible();

  await page.getByLabel("Source URL").fill("https://x.example/feed.xml");
  await page.getByRole("button", { name: "Add source" }).click();
  await expect(list.getByText("https://x.example/feed.xml")).toBeVisible();
});

test("a check surfaces per-item fetch failures with a typed reason (M13.1, M16.1)", async ({
  page,
}) => {
  await openTracking(page);
  await page.getByRole("button", { name: "Check for new items" }).click();

  // the summary never reads "all ok" when items failed (beta P0-1) — and it
  // counts sources/items only, never verification outcomes (M16.1)
  await expect(page.getByRole("status")).toContainText("2 items couldn't be fetched");
  await expect(page.getByRole("status")).not.toContainText(/verified|corroboration/);
  // the flagged source shows the typed reason; the /check paste link is retired
  const flagged = page.getByRole("list", { name: "Sources this check flagged" });
  await expect(flagged).toContainText("federalreserve.gov");
  await expect(flagged).toContainText(/articles themselves can't be fetched/);
  await expect(flagged.getByRole("link")).toHaveCount(0);
});
