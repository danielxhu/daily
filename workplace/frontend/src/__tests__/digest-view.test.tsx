import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DigestView } from "@/components/DigestView";
import type { queryBoards, queryModules } from "@/lib/api";
import { queryDigest } from "@/lib/api";
import { buildMockBoards, buildMockDigest, buildMockModules } from "@/mocks/fixtures";

function setup(digestFn?: typeof queryDigest) {
  const fn = vi.fn(digestFn ?? (async () => buildMockDigest()));
  render(<DigestView digestFn={fn as unknown as typeof queryDigest} />);
  return { fn };
}

// M16.1 (check retirement): the digest IS the tracked-items channel. The
// verified-fact categories, credibility, heat, and verdict flags are dormant —
// even when the API still returns `items`, the UI renders none of them.

describe("DigestView", () => {
  it("shows a loading state while the digest is being fetched", () => {
    setup((() => new Promise<never>(() => {})) as unknown as typeof queryDigest);
    expect(screen.getByText("Loading the digest…")).toBeInTheDocument();
  });

  it("renders the tracked channel with lite signals and zero check language", async () => {
    setup();
    const section = await screen.findByRole("region", { name: "New from your sources" });
    // a clean item: provenance link + tier + the BILINGUAL enrichment rendered
    // in the active locale (en by default); the legacy line never renders
    expect(
      within(section).getByRole("link", { name: "SEC statement on market-structure rulemaking" }),
    ).toHaveAttribute("href", "/items/ti_sec");
    expect(
      within(section).getByText("The source says its market-structure rulemaking enters a comment period."),
    ).toBeInTheDocument();
    expect(within(section).getByText("AI summary")).toBeInTheDocument();
    expect(within(section).queryByText(/LEGACY-ONLY/)).toBeNull();
    // the non-enriched (degraded) item still shows the honest pending state
    expect(within(section).getByText("AI summary pending")).toBeInTheDocument();
    expect(within(section).getByText("T1 · primary/official")).toBeInTheDocument();
    // a degraded item stays visible with a typed status — never hidden
    expect(within(section).getByText("Markets Daily — episode 214")).toBeInTheDocument();
    expect(
      within(section).getByText("fetched · processing didn't finish — will retry"),
    ).toBeInTheDocument();
    // the fact categories and their annotations are dormant: none render
    expect(screen.queryByRole("region", { name: "Earnings" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Policy" })).toBeNull();
    expect(document.body.textContent).not.toMatch(
      /confidence · \d+\/100|Verdict changed|Heat \d|independent source/i,
    );
  });

  it("renders no legacy summary text anywhere — render stays cache-only (M14.7/M16.1)", async () => {
    setup();
    await screen.findByRole("region", { name: "New from your sources" });
    // the deprecated single-language line never renders; render stays cache-only
    expect(screen.queryByText(/Summaries are AI-generated/)).toBeNull();
    expect(document.body.textContent).not.toMatch(/LEGACY-ONLY/);
  });

  it("defaults the view window to a month and refetches when the user adjusts it (M14.6)", async () => {
    const { fn } = setup();
    await screen.findByRole("region", { name: "New from your sources" });
    // owner: "近期的所有变化,默认一个月" — the first fetch asks for 30 days
    expect(fn).toHaveBeenCalledWith({ windowDays: 30 });
    // "后续用户可以调整时长" — switching the range refetches
    fireEvent.change(screen.getByLabelText("Time range"), { target: { value: "7" } });
    await waitFor(() => expect(fn).toHaveBeenCalledWith({ windowDays: 7 }));
  });

  it("shows an empty state that guides to Sources", async () => {
    setup(
      (async () => ({
        date: "2026-06-09",
        items: [],
        generated_at: "2026-06-09T08:00:00+00:00",
        tracked: [],
      })) as unknown as typeof queryDigest,
    );
    await waitFor(() =>
      expect(screen.getByText(/Nothing new from your sources yet/)).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "Sources" })).toHaveAttribute("href", "/tracking");
  });

  it("surfaces an API error", async () => {
    setup(
      (async () => {
        throw new Error("boom");
      }) as unknown as typeof queryDigest,
    );
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Could not load the digest."),
    );
  });
});

// --- M16.6: board/module grouping + per-group stats -----------------------------

describe("DigestView grouped read surface (M16.6)", () => {
  it("groups by board with module sub-heads and code-computed group stats", async () => {
    const boardsFn = vi.fn(async () => buildMockBoards());
    const modulesFn = vi.fn(async (boardId: string) => buildMockModules(boardId));
    render(
      <DigestView
        digestFn={vi.fn(async () => buildMockDigest()) as unknown as typeof queryDigest}
        boardsFn={boardsFn as unknown as typeof queryBoards}
        modulesFn={modulesFn as unknown as typeof queryModules}
      />,
    );
    // the board group carries its module sub-head + the stats line
    const econ = await screen.findByRole("region", { name: "经济" });
    expect(within(econ).getByRole("heading", { level: 4, name: "Rates" })).toBeInTheDocument();
    expect(within(econ).getByText(/items 1 · sources 1 · latest .+ · T1 ×1/)).toBeInTheDocument();
    // the board-less item lands honestly in the labeled bucket, never hidden
    const none = screen.getByRole("region", { name: "No board yet" });
    expect(within(none).getByText("Markets Daily — episode 214")).toBeInTheDocument();
    // module names are fetched ONLY for boards that have module-tagged items
    expect(modulesFn).toHaveBeenCalledTimes(1);
    expect(modulesFn).toHaveBeenCalledWith("b_economy");
  });
});

