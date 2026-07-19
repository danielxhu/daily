import { expect, test, type Page } from "@playwright/test";

// Open a page and wait for the mock worker before interacting.
async function openMockApp(page: Page, path = "/") {
  await page.goto(path);
  await expect(page.locator("html[data-msw-ready='true']")).toBeAttached({
    timeout: 30_000,
  });
}

// Boards browse lives inside the Knowledge page (M12.4). Reach it via the primary
// nav and open the Finance board. We navigate client-side (rather than a direct
// goto) so MSW is ready before BoardsView mounts and fetches the board list — a
// direct load would race worker startup.
async function openFinanceBoard(page: Page) {
  await openMockApp(page);
  // exact: the first-run guide's "Ask Knowledge" link also contains "Knowledge"
  await page.getByRole("link", { name: "Knowledge", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Knowledge", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Finance", exact: true }).click();
}

test("open a board: notes render, no check-era or distill surface", async ({ page }) => {
  await openFinanceBoard(page);

  await expect(page.getByRole("region", { name: "Notes" })).toBeVisible();
  // engine removal (2026-07-13): no AI summary region, no verified-facts region
  await expect(page.getByRole("region", { name: "AI summary" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Verified facts" })).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(
    /verified fact|source of truth|credibility|verdict|stance|已核查事实|事实层|非信源/i,
  );
});

test("delete a board after the honest two-step confirm (M14.2)", async ({ page }) => {
  await openFinanceBoard(page);
  await page.getByRole("button", { name: "Delete board" }).click();
  // the confirm covers every real consequence: the board, its TRACKED SOURCES
  // (board-scoped subscriptions are deleted with it), and its notes go
  await expect(
    page.getByText(/the tracked sources assigned to it.*Nothing else is affected/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Delete it" }).click();
  // the chip disappears; selection falls back to the first preset board
  await expect(page.getByRole("button", { name: "Finance", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "政治" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("knowledge hierarchy: create a module, move a source, filter items (M15.3)", async ({ page }) => {
  await openFinanceBoard(page);
  const section = page.getByRole("region", { name: "Modules and sources" });

  // the reading surface: module chips + tracked items, no admin chrome yet
  await expect(section.getByRole("button", { name: "Rates", exact: true })).toBeVisible();
  await expect(
    section.getByRole("link", { name: "Board-scoped tracked item" }),
  ).toBeVisible();
  await expect(section.getByLabel("New module name")).toHaveCount(0);

  // management chrome (module add/delete, source module moves) is behind Manage
  await page.getByRole("button", { name: "Manage", exact: true }).click();

  // create a module (stateful mock: it appears as a chip)
  await section.getByLabel("New module name").fill("AI chips");
  await section.getByRole("button", { name: "Add", exact: true }).click();
  await expect(section.getByRole("button", { name: "AI chips", exact: true })).toBeVisible();

  // move the board's source into it
  await section.getByLabel(/Module:/).first().selectOption({ label: "AI chips" });

  // filter by the new module: the tracked item (ungrouped) drops out honestly
  await section.getByRole("button", { name: "AI chips", exact: true }).click();
  await expect(section.getByRole("link", { name: "Board-scoped tracked item" })).toHaveCount(0);
  await expect(section.getByText(/No tracked items here yet/)).toBeVisible();
  await section.getByRole("button", { name: "All", exact: true }).click();
  await expect(
    section.getByRole("link", { name: "Board-scoped tracked item" }),
  ).toBeVisible();

  // the hierarchy must not squeeze the page sideways (mobile project included)
  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 1,
  );
  expect(noOverflow).toBe(true);
});
