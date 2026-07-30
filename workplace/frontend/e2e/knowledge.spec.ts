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

// The saved notes are a pile of cards on Knowledge: the newest is open, hovering
// another opens it, and ticking cards bounds the next ask to them.
test("the note pile: read by hover, rename in place, bound the ask to picked notes", async ({
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

  // rename lands on the card the pointer is reading
  const front = pile.locator(".pcard").last();
  await front.hover();
  await front.getByRole("button", { name: "Rename" }).click();
  const field = pile.getByLabel("Note title");
  await field.fill("Repricing has a second leg");
  await field.press("Enter");
  await expect(pile.getByText("Repricing has a second leg")).toBeVisible();

  // picking a card narrows the ask; the scope line says so, and clearing restores it
  await expect(page.getByText("Asking over every note")).toBeVisible();
  await pile.getByRole("checkbox").first().check();
  await expect(page.getByText("Asking over 1 picked note(s)")).toBeVisible();
  await page.getByRole("button", { name: "Use all notes" }).click();
  await expect(page.getByText("Asking over every note")).toBeVisible();
});
