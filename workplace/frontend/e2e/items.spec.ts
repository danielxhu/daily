import { expect, test, type Page } from "@playwright/test";

// Open the app and wait for the mock worker before interacting.
async function openMockApp(page: Page, path = "/") {
  await page.goto(path);
  await expect(page.locator("html[data-msw-ready='true']")).toBeAttached({
    timeout: 30_000,
  });
}

// M16.4: every tracked item has its own detail page — the owner's "点进任何一条
// 信息" entry point. Everything stays in tracking language.

test("click an item on Today → its detail page: summary + the LLM-curated note flow", async ({
  page,
}) => {
  await openMockApp(page);
  await page
    .getByRole("link", { name: "SEC statement on market-structure rulemaking" })
    .click();

  // header + original link
  await expect(
    page.getByRole("heading", { name: "SEC statement on market-structure rulemaking", level: 1 }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "original ↗" }).first()).toHaveAttribute(
    "href",
    "https://www.sec.gov/news/press-release/2026-99",
  );
  // the AI summary (active locale)
  await expect(
    page.getByText("The source says its market-structure rulemaking enters a comment period."),
  ).toBeVisible();
  // the raw excerpt, provenance and related blocks all left the page (2026-07-13)
  await expect(page.getByRole("region", { name: "Source says" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Source & provenance" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Similar & related" })).toHaveCount(0);

  // the note is LLM-curated first (2026-07-13): draft → chat revision → save
  await page.getByRole("button", { name: "Draft a note" }).click();
  await expect(page.getByText(/要点:市场结构规则进入公开评议期/)).toBeVisible();
  await expect(page.getByText("AI draft — not saved yet")).toBeVisible();
  await page
    .getByRole("textbox", { name: "How should the draft change" })
    .fill("补上评议截止日期");
  await page.getByRole("button", { name: "Revise" }).click();
  await expect(page.getByText(/修订稿.*按「补上评议截止日期」/)).toBeVisible();
  await page.getByRole("button", { name: "Save to Knowledge" }).click();
  await expect(page.getByText("Saved to Knowledge.")).toBeVisible();
  // no check language anywhere on the page
  await expect(page.locator("body")).not.toContainText(/credibility|verdict|\/100|deep check/i);
});

test("a pending item fetches + summarizes automatically on open (no click)", async ({
  page,
}) => {
  await openMockApp(page);
  // the podcast item has no enrichment in the fixture (degraded → pending);
  // opening its detail page starts fetch-&-summarize by itself (2026-07-10)
  await page.getByRole("link", { name: "Markets Daily — episode 214" }).click();
  await expect(
    page.getByText("The source says this episode discusses market trends."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Fetch & summarize" })).toHaveCount(0);
  // …and the discussion opens up in place, now that grounding material exists
  await expect(
    page.getByRole("textbox", { name: "Your question about this item" }),
  ).toBeVisible();
});

// M16.5: the second half of the owner's "点进任何一条信息都可以和 chat 讨论" —
// an item-bounded discussion right on the detail page.
test("discuss an item on its detail page: source-bounded reply, honest limits", async ({
  page,
}) => {
  await openMockApp(page);
  await page
    .getByRole("link", { name: "SEC statement on market-structure rulemaking" })
    .click();

  const panel = page.getByRole("region", { name: "Discuss this item" });
  await expect(panel.getByText("Discuss this item with AI.")).toBeVisible();
  await panel
    .getByRole("textbox", { name: "Your question about this item" })
    .fill("评议期什么时候结束?");
  await panel.getByRole("button", { name: "Send" }).click();

  // the user turn + the mock's reply: source fact, then labeled analysis
  await expect(panel.getByText("评议期什么时候结束?", { exact: true })).toBeVisible();
  await expect(panel.getByText(/来源提到规则进入公开评议期;由此看/)).toBeVisible();
  // still zero check language anywhere on the page
  await expect(page.locator("body")).not.toContainText(/credibility|verdict|\/100|deep check/i);
});
