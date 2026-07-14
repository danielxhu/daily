import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ItemDetailView } from "@/components/ItemDetailView";
import { createNote, getTrackedItem, refreshTrackedItem } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n";
import type { TrackedItemCard, TrackedItemDetail } from "@/types/contract";

const enrichedItem: TrackedItemCard = {
  id: "ti1",
  board_id: "b_economy",
  module_id: null,
  url: "https://www.sec.gov/news/x",
  title: "SEC adopts market-structure rules",
  domain: "sec.gov",
  tier: "T1",
  published: "2026-07-01T07:00:00+00:00",
  first_seen: "2026-07-01T07:10:00+00:00",
  status: "fetched",
  failure_kind: null,
  degraded_reason: null,
  summary: "LEGACY-ONLY: must never render.",
  enrichment: {
    summary_zh: "来源称规则进入评议期。",
    summary_en: "The source says the rules enter a comment period.",
    why_zh: "与市场结构监管相关。",
    why_en: "Relevant to market-structure regulation.",
    entities: ["SEC"],
    tags: ["policy"],
    limitations_zh: "仅基于节选。",
    limitations_en: "Based on an excerpt only.",
  },
  content_available: true,
  similar_count: 0,
};

const related: TrackedItemCard = {
  ...enrichedItem,
  id: "ti2",
  title: "Same story elsewhere",
  domain: "media.example.com",
  tier: "T2",
  enrichment: null,
  content_available: false,
};

function detail(overrides: Partial<TrackedItemDetail> = {}): TrackedItemDetail {
  return {
    item: enrichedItem,
    excerpt_preview: "The Securities and Exchange Commission today announced…",
    fetch_method: "trafilatura",
    related: [related],
    ...overrides,
  };
}

function setup(d: TrackedItemDetail, fns: {
  refreshFn?: typeof refreshTrackedItem;
  createNoteFn?: typeof createNote;
} = {}) {
  const detailFn = vi.fn(async () => d);
  render(
    <LocaleProvider>
      <ItemDetailView
        itemId={d.item.id}
        detailFn={detailFn as unknown as typeof getTrackedItem}
        refreshFn={fns.refreshFn}
        createNoteFn={fns.createNoteFn}
      />
    </LocaleProvider>,
  );
  return { detailFn };
}

describe("ItemDetailView (M16.4)", () => {
  beforeEach(() => window.localStorage.clear());

  it("renders summary, source excerpt, provenance and related — zero check language", async () => {
    setup(detail());
    // header: title + original link
    expect(
      await screen.findByRole("heading", { name: "SEC adopts market-structure rules" }),
    ).toBeInTheDocument();
    // (.getAllBy…[0]: the related row's lite card carries its own original link)
    expect(screen.getAllByRole("link", { name: "original ↗" })[0]).toHaveAttribute(
      "href",
      "https://www.sec.gov/news/x",
    );
    // AI summary in the active locale (en), labeled + why/tags/entities/limits
    expect(
      screen.getByText("The source says the rules enter a comment period."),
    ).toBeInTheDocument();
    expect(screen.getByText("Relevant to market-structure regulation.")).toBeInTheDocument();
    expect(screen.getByText("policy")).toBeInTheDocument();
    expect(screen.getByText(/Named in the source: SEC/)).toBeInTheDocument();
    expect(screen.getByText(/Based on an excerpt only/)).toBeInTheDocument();
    expect(screen.getByText(/AI-generated from the source text/)).toBeInTheDocument();
    // owner 2026-07-10: the raw excerpt no longer renders — the briefing carries it
    expect(screen.queryByRole("region", { name: "Source says" })).toBeNull();
    // provenance
    const prov = screen.getByRole("region", { name: "Source & provenance" });
    expect(within(prov).getByText("trafilatura")).toBeInTheDocument();
    expect(within(prov).getByText("T1 · primary/official")).toBeInTheDocument();
    // related — rendered with the shared lite row, linking to ITS detail page
    const rel = screen.getByRole("region", { name: "Similar & related" });
    expect(within(rel).getByRole("link", { name: "Same story elsewhere" })).toHaveAttribute(
      "href",
      "/items/ti2",
    );
    // the check surface stays retired + the legacy line stays dead
    expect(document.body.textContent).not.toMatch(
      /credibility|verdict|stance|deep check|\/100|LEGACY-ONLY/i,
    );
  });

  it("follows the zh locale for summary, why and limits", async () => {
    window.localStorage.setItem("daily.locale", "zh");
    setup(detail());
    expect(await screen.findByText("来源称规则进入评议期。")).toBeInTheDocument();
    expect(screen.getByText("与市场结构监管相关。")).toBeInTheDocument();
    expect(screen.getByText(/仅基于节选/)).toBeInTheDocument();
    expect(
      screen.queryByText("The source says the rules enter a comment period."),
    ).toBeNull();
  });

  it("a pending item fetches + summarizes AUTOMATICALLY on open (2026-07-10)", async () => {
    const pending = detail({
      item: { ...enrichedItem, enrichment: null, content_available: false },
      excerpt_preview: null,
      fetch_method: null,
    });
    const refreshFn = vi.fn(async () => detail());
    setup(pending, { refreshFn: refreshFn as unknown as typeof refreshTrackedItem });

    // no click anywhere: opening the page starts the fetch and the summary lands
    await waitFor(() => expect(refreshFn).toHaveBeenCalledWith("ti1"));
    expect(
      await screen.findByText("The source says the rules enter a comment period."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fetch & summarize" })).toBeNull();
  });

  it("a REAL failure (typed 502) surfaces with the button as the manual retry", async () => {
    const pending = detail({
      item: { ...enrichedItem, enrichment: null, content_available: false },
      excerpt_preview: null,
    });
    const refreshFn = vi.fn(async () => {
      const { ApiError } = await import("@/lib/api");
      throw new ApiError(502, "fetch failed (anti_bot) — try again later");
    });
    setup(pending, { refreshFn: refreshFn as unknown as typeof refreshTrackedItem });
    // a non-transient failure ends the auto attempt loudly; the button = retry
    expect(await screen.findByRole("alert")).toHaveTextContent(/anti_bot/);
    expect(refreshFn).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Fetch & summarize" }));
    await waitFor(() => expect(refreshFn).toHaveBeenCalledTimes(2));
  });

  it("a TRANSIENT failure (busy 409) retries quietly until it succeeds (2026-07-13)", async () => {
    vi.useFakeTimers();
    try {
      const pending = detail({
        item: { ...enrichedItem, enrichment: null, content_available: false },
        excerpt_preview: null,
      });
      let calls = 0;
      const refreshFn = vi.fn(async () => {
        calls += 1;
        if (calls === 1) {
          const { ApiError } = await import("@/lib/api");
          throw new ApiError(409, "the tracker is busy — try again in a moment");
        }
        return detail();
      });
      setup(pending, { refreshFn: refreshFn as unknown as typeof refreshTrackedItem });
      // first (auto) attempt hits busy — NO error shows, the quiet retry waits
      await vi.waitFor(() => expect(refreshFn).toHaveBeenCalledTimes(1));
      expect(screen.queryByRole("alert")).toBeNull();
      await vi.advanceTimersByTimeAsync(10_000);
      await vi.waitFor(() => expect(refreshFn).toHaveBeenCalledTimes(2));
      vi.useRealTimers();
      // the second attempt landed the summary — still zero clicks
      expect(
        await screen.findByText("The source says the rules enter a comment period."),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("saves a note into the item's board as a searchable user note", async () => {
    const createNoteFn = vi.fn(async () => ({}) as never);
    setup(detail(), { createNoteFn: createNoteFn as unknown as typeof createNote });
    const noteBox = await screen.findByRole("textbox", { name: "Your note" });
    fireEvent.change(noteBox, { target: { value: "watch the July filing" } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() =>
      expect(createNoteFn).toHaveBeenCalledWith("b_economy", {
        kind: "user_note",
        content: "watch the July filing",
      }),
    );
    expect(await screen.findByText("Saved to Knowledge.")).toBeInTheDocument();
  });

  it("explains when the item has no board — notes need a board's Knowledge", async () => {
    setup(detail({ item: { ...enrichedItem, board_id: null } }));
    expect(
      await screen.findByText(/Assign this item's source to a board first/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save note" })).toBeNull();
  });

  it("a missing item is a typed not-found, with a way back", async () => {
    const detailFn = vi.fn(async () => {
      const { ApiError } = await import("@/lib/api");
      throw new ApiError(404, "no such tracked item: nope");
    });
    render(
      <LocaleProvider>
        <ItemDetailView itemId="nope" detailFn={detailFn as unknown as typeof getTrackedItem} />
      </LocaleProvider>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/does not exist/);
    expect(screen.getByRole("link", { name: "← Today" })).toHaveAttribute("href", "/");
  });
});
