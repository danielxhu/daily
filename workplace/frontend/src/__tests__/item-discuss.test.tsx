import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ItemDetailView } from "@/components/ItemDetailView";
import { ApiError, discussTrackedItem, getTrackedItem } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n";
import type { TrackedItemCard, TrackedItemDetail } from "@/types/contract";

const item: TrackedItemCard = {
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
  summary: null,
  enrichment: {
    summary_zh: "来源称规则进入评议期。",
    summary_en: "The source says the rules enter a comment period.",
    why_zh: null,
    why_en: null,
    entities: [],
    tags: [],
    limitations_zh: null,
    limitations_en: null,
  },
  content_available: true,
  similar_count: 0,
};

function detail(overrides: Partial<TrackedItemDetail> = {}): TrackedItemDetail {
  return {
    item,
    excerpt_preview: "The Commission announced its rulemaking enters a comment period.",
    ...overrides,
  };
}

function setup(d: TrackedItemDetail, discussFn: typeof discussTrackedItem) {
  render(
    <LocaleProvider>
      <ItemDetailView
        itemId={d.item.id}
        detailFn={vi.fn(async () => d) as unknown as typeof getTrackedItem}
        discussFn={discussFn}
      />
    </LocaleProvider>,
  );
}

describe("ItemDiscussPanel (M16.5)", () => {
  beforeEach(() => window.localStorage.clear());

  it("sends a question and renders the source-bounded reply — zero check language", async () => {
    const discussFn = vi.fn(async () => ({
      reply: "来源称:评议期于 7 月开始。证据不足以回答时长。",
    }));
    setup(detail(), discussFn as unknown as typeof discussTrackedItem);

    const panel = await screen.findByRole("region", { name: "Discuss this item" });
    expect(within(panel).getByText("Discuss this item with AI.")).toBeInTheDocument();
    fireEvent.change(within(panel).getByRole("textbox", { name: "Your question about this item" }), {
      target: { value: "评议期多久?" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Send" }));

    // the user's turn shows immediately; the reply lands after the call
    expect(within(panel).getByText("评议期多久?")).toBeInTheDocument();
    expect(await within(panel).findByText(/评议期于 7 月开始/)).toBeInTheDocument();
    await waitFor(() =>
      expect(discussFn).toHaveBeenCalledWith("ti1", [{ role: "user", content: "评议期多久?" }]),
    );
    // the check surface stays retired
    expect(document.body.textContent).not.toMatch(/credibility|verdict|stance|deep check|\/100/i);
  });

  it("carries the whole conversation into the next turn", async () => {
    const discussFn = vi.fn(async () => ({ reply: "来源称进入评议期。" }));
    setup(detail(), discussFn as unknown as typeof discussTrackedItem);

    const panel = await screen.findByRole("region", { name: "Discuss this item" });
    const box = within(panel).getByRole("textbox", { name: "Your question about this item" });
    fireEvent.change(box, { target: { value: "first" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Send" }));
    await within(panel).findAllByText("来源称进入评议期。");
    fireEvent.change(box, { target: { value: "second" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(discussFn).toHaveBeenLastCalledWith("ti1", [
        { role: "user", content: "first" },
        { role: "assistant", content: "来源称进入评议期。" },
        { role: "user", content: "second" },
      ]),
    );
  });

  it("a failed reply is a typed, retryable error — the question is not lost", async () => {
    const discussFn = vi.fn(async () => {
      throw new ApiError(502, "discussion failed: llm down");
    });
    setup(detail(), discussFn as unknown as typeof discussTrackedItem);

    const panel = await screen.findByRole("region", { name: "Discuss this item" });
    fireEvent.change(within(panel).getByRole("textbox", { name: "Your question about this item" }), {
      target: { value: "hi" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Send" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent(/discussion failed/);
    // the user's turn stays in the log and the input is ready for a retry
    expect(within(panel).getByText("hi")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("without stored text it points at Fetch & summarize instead of a dead chat", async () => {
    const bare = detail({
      item: { ...item, enrichment: null, content_available: false },
      excerpt_preview: null,
    });
    setup(bare, vi.fn() as unknown as typeof discussTrackedItem);

    const panel = await screen.findByRole("region", { name: "Discuss this item" });
    expect(within(panel).getByText(/needs this item's stored text/)).toBeInTheDocument();
    expect(within(panel).queryByRole("textbox")).toBeNull();
  });

  it("follows the zh locale for the panel copy", async () => {
    window.localStorage.setItem("daily.locale", "zh");
    setup(detail(), vi.fn() as unknown as typeof discussTrackedItem);
    const panel = await screen.findByRole("region", { name: "讨论这条信息" });
    expect(within(panel).getByText("和 AI 讨论一下这条消息。")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "发送" })).toBeInTheDocument();
  });
});
