import { expect, test, type Page } from "@playwright/test";

// Open a page and wait for the mock worker before interacting.
async function openMockApp(page: Page, path = "/") {
  // returning-user flag: the first-visit welcome redirect has its own spec
  await page.addInitScript(() => window.localStorage.setItem("daily.onboarded", "1"));
  await page.goto(path);
  await expect(page.locator("html[data-msw-ready='true']")).toBeAttached({
    timeout: 30_000,
  });
}

// 2026-07-24: every ask is a persisted chat — answered in one call, reopenable,
// continuable from the history list.
test("an ask becomes a persisted chat: answer renders, history lists it", async ({ page }) => {
  await openMockApp(page);
  // exact: the first-run guide's "Ask Knowledge" link also contains "Knowledge"
  await page.getByRole("link", { name: "Knowledge", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Knowledge", level: 1 })).toBeVisible();

  await page.getByRole("textbox", { name: "Ask daily" }).fill("fed merger");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  // the labeled answer renders inside the conversation
  await expect(page.getByText("AI answer", { exact: true })).toBeVisible();
  await expect(page.getByText(/mock 回答/).first()).toBeVisible();

  // …and the chat is persisted: the history section lists it by its question
  await expect(page.getByText("Chat history")).toBeVisible();
  const history = page.getByRole("list", { name: "Previous chats" }).first();
  await expect(history.getByText(/fed merger/)).toBeVisible();

  // a follow-up continues the same chat (both turns visible)
  await page.getByRole("textbox", { name: "Ask daily" }).fill("what changed?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByText(/接着聊/).first()).toBeVisible();
});

// M16.7: the knowledge map — board cards with counts — and the layered search.
test("the notes carry a board filter, and the check surface stays retired", async ({ page }) => {
  await openMockApp(page);
  await page.getByRole("link", { name: "Knowledge", exact: true }).click();

  // the board card grid left the page; the notes have their own segmented filter
  const filter = page.getByRole("group", { name: "Board filter" });
  await expect(filter.getByRole("button", { name: "All" })).toBeVisible();
  await filter.getByRole("button", { name: "Finance" }).click();
  await expect(page.getByRole("region", { name: "Your notes" })).toBeVisible();

  await expect(page.locator("body")).not.toContainText(/credibility|verdict|\/100|deep check/i);
});

// The saved notes are a pile of cards on Knowledge: the newest is open, hovering
// another opens it, and every note starts picked — clicking one leaves it out.
test("the note pile: read by hover, click to leave a note out of the ask", async ({
  page,
}) => {
  await openMockApp(page, "/knowledge");
  const pile = page.getByRole("region", { name: "Your notes" });
  await expect(pile).toBeVisible();

  // the newest note is the front of the pile, so its body is readable at rest
  await expect(
    pile.getByText("Spreads widened through Q2, but the two houses disagree on why."),
  ).toBeVisible();

  // hovering the older card opens it in place
  const older = pile.locator(".pcard").first();
  await older.hover();
  await expect(older).toHaveAttribute("data-open", "1");

  // every note starts picked; clicking a card leaves it out, and one click restores
  await expect(page.getByText("Asking over every note")).toBeVisible();
  await expect(pile.getByRole("checkbox").first()).toBeChecked();
  await older.click();
  await expect(page.getByText("Asking over 1 picked note(s)")).toBeVisible();
  await page.getByRole("button", { name: "Use all notes" }).click();
  await expect(page.getByText("Asking over every note")).toBeVisible();
});

// A note saved before the bilingual copies existed only follows the language switch
// once the user asks for the other language on the note's own page.
test("open a note: edit its body, then have it written in the other language", async ({
  page,
}) => {
  await openMockApp(page, "/knowledge");
  const pile = page.getByRole("region", { name: "Your notes" });
  const older = pile.locator(".pcard").first();
  await older.hover();
  await older.getByRole("link", { name: "Open" }).click();

  const body = page.getByLabel("Note", { exact: true });
  await expect(body).toBeVisible();
  await body.fill("SEC 规则进入公开评议期,截止日期需回原文确认。补一句:关注最终稿。");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();

  // the note has no English copy yet, so the switch is offered explicitly
  await page.getByRole("button", { name: /Write this note in Chinese too/ }).click();
  await expect(page.getByText("This note now follows the language switch.")).toBeVisible();
});
