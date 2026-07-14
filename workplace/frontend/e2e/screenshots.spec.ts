import { expect, test, type Page } from "@playwright/test";

// M9.5 — capture a full-page screenshot of every top-level view on BOTH the desktop
// and mobile Playwright projects, and assert each one (a) carries the app-wide
// credibility honesty disclaimer and (b) does not overflow horizontally (text-fit /
// mobile). The screenshots are the "doesn't look half-finished" review evidence.

async function open(page: Page, path: string) {
  await page.goto(path);
  await expect(page.locator("html[data-msw-ready='true']")).toBeAttached({ timeout: 30_000 });
  // mount fetches are gated on the worker (lib/api waitForMock), so once the worker
  // is ready the real (mock) content settles — wait for it so screenshots show it
  await page.waitForLoadState("networkidle");
  // let the staggered entrance (Reveal) finish so full-page shots show every section
  await page.waitForFunction(
    () => document.querySelectorAll(".reveal:not(.revealed)").length === 0,
  );
  await page.waitForTimeout(900); // transition (0.5s) + max stagger (0.3s)
}

const VIEWS = [
  { path: "/", name: "today" },
  { path: "/tracking", name: "sources" },
  { path: "/knowledge", name: "knowledge" },
  { path: "/digest", name: "digest" },
  { path: "/trace", name: "trace" },
];

for (const view of VIEWS) {
  test(`screenshot · ${view.name} · no check language + no overflow`, async ({ page }, info) => {
    await open(page, view.path);

    // M16.1 (check retirement): no user-visible score/verdict/credibility language
    // anywhere — the honest boundaries are phrased in tracking terms instead
    await expect(page.locator("body")).not.toContainText(
      /credibility|deep check|\/100|verdict/i,
    );

    // exactly ONE main landmark (layout owns it; pages must not nest their own)
    await expect(page.locator("main")).toHaveCount(1);

    // no horizontal overflow on this viewport (text-fit / mobile hardening)
    const noOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    );
    expect(noOverflow).toBe(true);

    await page.screenshot({
      path: info.outputPath(`${view.name}-${info.project.name}.png`),
      fullPage: true,
    });
  });
}
