import { expect, test, type Page } from "@playwright/test";

// Open a page and wait for the mock worker before interacting.
async function openMockApp(page: Page, path = "/") {
  await page.goto(path);
  await expect(page.locator("html[data-msw-ready='true']")).toBeAttached({
    timeout: 30_000,
  });
}

// Reach the digest via the nav so MSW is ready before DigestView mounts and fetches.
async function openDigest(page: Page) {
  await openMockApp(page);
  // let the staggered entrance settle — footer links shift while Reveal runs,
  // which makes mobile taps land on the moving container instead of the link
  await page.waitForFunction(
    () => document.querySelectorAll(".reveal:not(.revealed)").length === 0,
  );
  await page.getByRole("link", { name: "Full digest", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Digest", level: 1 })).toBeVisible();
}

// M16.1 (check retirement): the digest IS the tracked-items channel — what the
// user's sources published recently, with lite signals and cached AI summaries.
// The verified categories, credibility, heat, and verdict flags are dormant.

test("read the digest: tracked items with lite signals, no check language", async ({ page }) => {
  await openDigest(page);

  const section = page.getByRole("region", { name: "New from your sources" });
  // a clean item: provenance link + code-first tier + the bilingual enrichment
  // rendered in the active locale; the legacy line never renders (M16.1)
  await expect(
    section.getByRole("link", { name: "SEC statement on market-structure rulemaking" }),
  ).toBeVisible();
  await expect(
    section.getByText("The source says its market-structure rulemaking enters a comment period."),
  ).toBeVisible();
  await expect(section.getByText(/LEGACY-ONLY/)).toHaveCount(0);
  // the non-enriched (degraded) item shows the honest pending state
  await expect(section.getByText("AI summary pending")).toBeVisible();
  await expect(section.getByText("T1 · primary/official")).toBeVisible();
  // a degraded item stays visible with a typed, neutral status
  await expect(section.getByText("Markets Daily — episode 214")).toBeVisible();
  await expect(section.getByText("fetched · processing didn't finish — will retry")).toBeVisible();

  // the fact categories and their annotations are dormant
  await expect(page.getByRole("region", { name: "Earnings" })).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(/\/100|Verdict changed|Heat \d/);
});

test("the view window defaults to a month and is adjustable (M14.6)", async ({ page }) => {
  await openDigest(page);
  const range = page.getByLabel("Time range");
  await expect(range).toHaveValue("30");
  await range.selectOption("7");
  // the digest refetches and still renders the tracked channel
  await expect(
    page.getByRole("region", { name: "New from your sources" }),
  ).toBeVisible();
});

test("the AI summary follows the language toggle instantly (M16.3)", async ({ page }) => {
  await openDigest(page);
  const section = page.getByRole("region", { name: "New from your sources" });
  await expect(
    section.getByText("The source says its market-structure rulemaking enters a comment period."),
  ).toBeVisible();

  // owner 2026-07-08: "中英文切换的时候,给出的信息源的语言还是没有变化" — fixed:
  // both languages ride in the enrichment, so the switch is instant, no refetch.
  // (the section's accessible name follows the locale too — re-resolve it)
  await page.getByRole("button", { name: "Switch language" }).click();
  const sectionZh = page.getByRole("region", { name: "来源新内容" });
  await expect(sectionZh.getByText("来源称其市场结构规则制定进入公众评议期。")).toBeVisible();
  // 2026-07-10: the TITLE follows the toggle too (translated via the enrichment)
  await expect(
    sectionZh.getByRole("link", { name: "SEC 就市场结构规则制定发表声明" }),
  ).toBeVisible();
  await expect(
    sectionZh.getByText("The source says its market-structure rulemaking enters a comment period."),
  ).toHaveCount(0);
  await expect(sectionZh.getByText("AI 综述").first()).toBeVisible();
});

// M16.6: the AIHOT-informed read surface — board/module grouping + group stats.
test("the digest groups by board with module sub-heads and group stats (M16.6)", async ({
  page,
}) => {
  await openDigest(page);
  // the board group head + its code-computed stats line
  const econ = page.getByRole("region", { name: "经济" });
  await expect(econ.getByRole("heading", { name: "经济", level: 3 })).toBeVisible();
  await expect(econ.getByText(/items 1 · sources 1 · latest .+ · T1 ×1/)).toBeVisible();
  // the module name is a sub-head inside its board group
  await expect(econ.getByRole("heading", { name: "Rates", level: 4 })).toBeVisible();
  await expect(
    econ.getByRole("link", { name: "SEC statement on market-structure rulemaking" }),
  ).toBeVisible();
  // the board-less item lands honestly in the labeled bucket — never hidden
  const none = page.getByRole("region", { name: "No board yet" });
  await expect(none.getByText("Markets Daily — episode 214")).toBeVisible();
});
