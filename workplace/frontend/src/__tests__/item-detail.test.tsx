import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ItemDetailView } from "@/components/ItemDetailView";
import { createNote, draftItemNote, getTrackedItem, refreshTrackedItem } from "@/lib/api";
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

function detail(overrides: Partial<TrackedItemDetail> = {}): TrackedItemDetail {
  return {
    item: enrichedItem,
    excerpt_preview: "The Securities and Exchange Commission today announced…",
    ...overrides,
  };
}

function setup(d: TrackedItemDetail, fns: {
  refreshFn?: typeof refreshTrackedItem;
  createNoteFn?: typeof createNote;
  draftNoteFn?: typeof draftItemNote;
} = {}) {
  const detailFn = vi.fn(async () => d);
  render(
    <LocaleProvider>
      <ItemDetailView
        itemId={d.item.id}
        detailFn={detailFn as unknown as typeof getTrackedItem}
        refreshFn={fns.refreshFn}
        createNoteFn={fns.createNoteFn}
        draftNoteFn={fns.draftNoteFn}
      />
    </LocaleProvider>,
  );
  return { detailFn };
}

describe("ItemDetailView (M16.4)", () => {
  beforeEach(() => window.localStorage.clear());

  it("renders the summary — provenance/related gone (2026-07-13), zero check language", async () => {
    setup(detail());
    // header: title + original link
    expect(
      await screen.findByRole("heading", { name: "SEC adopts market-structure rules" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "original ↗" })).toHaveAttribute(
      "href",
      "https://www.sec.gov/news/x",
    );
    // AI summary in the active locale (en); the why/tags/entities/limits block
    // left the page (owner 2026-07-17)
    expect(
      screen.getByText("The source says the rules enter a comment period."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Relevant to market-structure regulation.")).toBeNull();
    expect(screen.queryByText(/Named in the source/)).toBeNull();
    expect(screen.queryByText(/AI-generated from the source text/)).toBeNull();
    // owner 2026-07-10: the raw excerpt no longer renders — the briefing carries it
    expect(screen.queryByRole("region", { name: "Source says" })).toBeNull();
    // owner 2026-07-13: the provenance and related blocks left the page
    expect(screen.queryByRole("region", { name: "Source & provenance" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Similar & related" })).toBeNull();
    // the check surface stays retired + the legacy line stays dead
    expect(document.body.textContent).not.toMatch(
      /credibility|verdict|stance|deep check|\/100|LEGACY-ONLY/i,
    );
  });

  it("follows the zh locale for the summary", async () => {
    window.localStorage.setItem("daily.locale", "zh");
    setup(detail());
    expect(await screen.findByText("来源称规则进入评议期。")).toBeInTheDocument();
    expect(
      screen.queryByText("The source says the rules enter a comment period."),
    ).toBeNull();
  });

  it("a pending item fetches + summarizes AUTOMATICALLY on open (2026-07-10)", async () => {
    const pending = detail({
      item: { ...enrichedItem, enrichment: null, content_available: false },
      excerpt_preview: null,
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

  it("drafts the note with the LLM, revises it through chat, saves only on click (2026-07-13)", async () => {
    const createNoteFn = vi.fn(async () => ({}) as never);
    const draftNoteFn = vi.fn(async (_id: string, messages: { content: string }[]) =>
      messages.length === 0
        ? { draft: "Key point: comment period opened." }
        : { draft: "Comment period opened; effective date pending." },
    );
    setup(detail(), {
      createNoteFn: createNoteFn as unknown as typeof createNote,
      draftNoteFn: draftNoteFn as unknown as typeof draftItemNote,
    });

    // step 1: the user asks daily for the initial curated draft
    fireEvent.click(await screen.findByRole("button", { name: "Draft a note" }));
    await waitFor(() => expect(draftNoteFn).toHaveBeenCalledWith("ti1", [], "en"));
    expect(await screen.findByText("Key point: comment period opened.")).toBeInTheDocument();
    expect(screen.getByText("AI draft — not saved yet")).toBeInTheDocument();
    // nothing saved yet
    expect(createNoteFn).not.toHaveBeenCalled();

    // step 2: a chat revision — the earlier draft + the instruction travel along
    fireEvent.change(screen.getByRole("textbox", { name: "How should the draft change" }), {
      target: { value: "mention the effective date" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Revise" }));
    await waitFor(() =>
      expect(draftNoteFn).toHaveBeenLastCalledWith(
        "ti1",
        [
          { role: "assistant", content: "Key point: comment period opened." },
          { role: "user", content: "mention the effective date" },
        ],
        "en",
      ),
    );
    expect(
      await screen.findByText("Comment period opened; effective date pending."),
    ).toBeInTheDocument();

    // step 3: only the explicit click saves — the CURRENT draft, as a user_note
    fireEvent.click(screen.getByRole("button", { name: "Save to Knowledge" }));
    await waitFor(() =>
      expect(createNoteFn).toHaveBeenCalledWith("b_economy", {
        kind: "user_note",
        content: "Comment period opened; effective date pending.",
      }),
    );
    expect(await screen.findByText("Saved to Knowledge.")).toBeInTheDocument();
  });

  it("explains when the item has no board — notes need a board's Knowledge", async () => {
    setup(detail({ item: { ...enrichedItem, board_id: null } }));
    expect(
      await screen.findByText(/Assign this item's source to a board first/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Draft a note" })).toBeNull();
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
