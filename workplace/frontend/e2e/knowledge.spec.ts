import { expect, test, type Page } from "@playwright/test";

// Open a page and wait for the mock worker before interacting.
async function openMockApp(page: Page, path = "/") {
  await page.goto(path);
  await expect(page.locator("html[data-msw-ready='true']")).toBeAttached({
    timeout: 30_000,
  });
}

// M16.2: search is instant and LLM-free; the AI answer is an explicit action.
test("search returns hits instantly; the AI answer only appears on demand", async ({ page }) => {
  await openMockApp(page);
  // exact: the first-run guide's "Ask Knowledge" link also contains "Knowledge"
  await page.getByRole("link", { name: "Knowledge", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Knowledge", level: 1 })).toBeVisible();

  await page.getByRole("textbox", { name: "Ask daily" }).fill("fed merger");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  // hits render: the saved note + a tracked item, labeled apart
  const saved = page.getByRole("list", { name: "Your saved notes" });
  await expect(saved.getByText(/Fed approved the merger/)).toBeVisible();
  await expect(page.getByText("From your sources").first()).toBeVisible();

  // no answer yet — search never synthesizes on its own
  await expect(page.getByText("AI answer", { exact: true })).toHaveCount(0);

  // the explicit action generates ONE labeled answer for this turn
  await page.getByRole("button", { name: "Generate AI answer" }).click();
  await expect(page.getByText(/the merger was approved/).first()).toBeVisible();
  await expect(page.getByText("AI answer", { exact: true })).toBeVisible();
  await expect(page.getByText(/only from your saved notes/)).toBeVisible();
});

// M16.7: the knowledge map — board cards with counts — and the layered search.
test("the knowledge map: board cards carry counts; search stays two-layered", async ({
  page,
}) => {
  await openMockApp(page);
  await page.getByRole("link", { name: "Knowledge", exact: true }).click();

  // board cards: name + code-computed counts (sources / recent items / notes)
  const econCard = page.getByRole("button", { name: "经济" });
  await expect(econCard).toBeVisible();
  await expect(econCard.getByText(/sources \d+ · items \d+ \(30d\) · notes \d+/)).toBeVisible();

  // …and the check surface stays retired on this page too
  await expect(page.locator("body")).not.toContainText(/credibility|verdict|\/100|deep check/i);
});
