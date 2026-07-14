import { expect, test, type Page } from "@playwright/test";

// Open a page and wait for the mock worker before interacting.
async function openMockApp(page: Page, path = "/") {
  await page.goto(path);
  await expect(page.locator("html[data-msw-ready='true']")).toBeAttached({
    timeout: 30_000,
  });
}

// Reach the trace via the nav so MSW is ready before TraceView mounts and fetches.
async function openTrace(page: Page) {
  await openMockApp(page);
  // let the staggered entrance settle — footer links shift while Reveal runs,
  // which makes mobile taps land on the moving container instead of the link
  await page.waitForFunction(
    () => document.querySelectorAll(".reveal:not(.revealed)").length === 0,
  );
  await page.getByRole("link", { name: "Run details" }).click();
  await expect(page.getByRole("heading", { name: "Run trace", level: 1 })).toBeVisible();
}

test("inspect a failed poll run: see where it got stuck", async ({ page }) => {
  await openTrace(page);

  const list = page.getByRole("list", { name: "Pipeline runs" });
  await expect(list.getByText("poll").first()).toBeVisible();
  // the failed run's typed per-item summary is visible
  await expect(list.getByText(/3\/3 new items failed ingestion: anti_bot ×3/)).toBeVisible();
  // one run failed, one is ok — both states visible at a glance
  await expect(list.getByText("failed").first()).toBeVisible();
  await expect(list.getByText("ok").first()).toBeVisible();
});
