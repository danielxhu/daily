import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { TrackedItemLite, TrackedItemsSection, type TrackedGrouping } from "@/components/TrackedItems";
import { LocaleProvider } from "@/lib/i18n";
import type { TrackedItemCard } from "@/types/contract";

const degraded: TrackedItemCard = {
  id: "ti1",
  board_id: null,
  module_id: null,
  url: "https://www.sec.gov/news/x",
  title: "SEC market-structure rules",
  domain: "sec.gov",
  tier: "T1",
  published: null,
  first_seen: "2026-07-07T00:00:00+00:00",
  status: "fetched",
  failure_kind: null,
  degraded_reason: "claim extraction failed — a later pass can retry",
  summary: null,
  similar_count: 0,
};

describe("TrackedItemLite after the check retirement (M16.1)", () => {
  it("shows title, provenance, tier and a typed degraded status — no check affordance", () => {
    render(<TrackedItemLite item={degraded} />);
    // the title opens the item's OWN detail page (M16.4) …
    expect(screen.getByRole("link", { name: "SEC market-structure rules" })).toHaveAttribute(
      "href",
      "/items/ti1",
    );
    // … and the original stays one click away in the meta line
    expect(screen.getByRole("link", { name: "original ↗" })).toHaveAttribute(
      "href",
      "https://www.sec.gov/news/x",
    );
    expect(screen.getByText("sec.gov")).toBeInTheDocument();
    // a degraded item states it honestly instead of hiding
    expect(screen.getByText("fetched · processing didn't finish — will retry")).toBeInTheDocument();
    // the check surface left the product: no deep-check entry, no score language
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText(/deep check/i)).toBeNull();
    expect(screen.queryByText(/credibility|score|verified/i)).toBeNull();
  });

  it("never renders the legacy single-language summary, even when the API returns it (M16.1)", () => {
    // the locale-blind `summary` stays in the contract but must not reach the
    // screen; without enrichment a fetched item shows a neutral pending state
    render(
      <TrackedItemLite
        item={{
          ...degraded,
          degraded_reason: null,
          summary: "The SEC says its rulemaking enters a comment period.",
        }}
      />,
    );
    expect(screen.queryByText(/rulemaking enters a comment period/)).toBeNull();
    expect(screen.getByText("AI summary pending")).toBeInTheDocument();
  });

  it("shows no pending line for failed items — the typed status speaks", () => {
    render(
      <TrackedItemLite
        item={{ ...degraded, status: "failed", failure_kind: "anti_bot", degraded_reason: null }}
      />,
    );
    expect(screen.queryByText("AI summary pending")).toBeNull();
    expect(screen.getByText(/anti-bot/)).toBeInTheDocument();
  });
});

describe("TrackedItemsSection (M16.1)", () => {
  it("renders the honest boundary note and the items", () => {
    render(<TrackedItemsSection items={[degraded]} />);
    expect(screen.getByRole("heading", { name: "New from your sources" })).toBeInTheDocument();
    // not real time + summaries only restate the source — the honesty boundary stays
    expect(screen.getByText(/not in real time/)).toBeInTheDocument();
    expect(screen.getByText(/only restate what the source says/)).toBeInTheDocument();
    expect(screen.getByText("SEC market-structure rules")).toBeInTheDocument();
  });

  it("renders the host's empty state when there are no items", () => {
    render(<TrackedItemsSection items={[]} empty={<p>nothing yet</p>} />);
    expect(screen.getByText("nothing yet")).toBeInTheDocument();
    expect(screen.queryByText(/only restate what the source says/)).toBeNull();
  });
});


describe("TrackedItemLite bilingual enrichment (M16.3)", () => {
  beforeEach(() => window.localStorage.clear());

  const enriched: TrackedItemCard = {
    ...degraded,
    degraded_reason: null,
    summary: "LEGACY-ONLY: must never render.",
    enrichment: {
      summary_zh: "来源称规则进入评议期。",
      summary_en: "The source says the rules enter a comment period.",
      why_zh: null,
      why_en: null,
      entities: ["SEC"],
      tags: ["policy"],
      limitations_zh: null,
      limitations_en: null,
    },
    content_available: true,
  };

  it("renders the English summary under the en locale, labeled AI", () => {
    render(
      <LocaleProvider>
        <TrackedItemLite item={enriched} />
      </LocaleProvider>,
    );
    expect(
      screen.getByText("The source says the rules enter a comment period."),
    ).toBeInTheDocument();
    expect(screen.getByText("AI summary")).toBeInTheDocument();
    // the zh text is NOT in the tree — the locale picks exactly one
    expect(screen.queryByText("来源称规则进入评议期。")).toBeNull();
    expect(screen.queryByText(/LEGACY-ONLY/)).toBeNull();
    expect(screen.queryByText(/pending/i)).toBeNull();
  });

  it("follows the zh locale instantly — the owner's language-toggle complaint", () => {
    // the saved zh choice upgrades the provider on mount (same as the app)
    window.localStorage.setItem("daily.locale", "zh");
    render(
      <LocaleProvider>
        <TrackedItemLite item={enriched} />
      </LocaleProvider>,
    );
    expect(screen.getByText("来源称规则进入评议期。")).toBeInTheDocument();
    expect(screen.getByText("AI 综述")).toBeInTheDocument(); // the label follows too
    expect(
      screen.queryByText("The source says the rules enter a comment period."),
    ).toBeNull();
    expect(screen.queryByText(/LEGACY-ONLY/)).toBeNull();
  });
});

// --- M16.6: the board/module-grouped read surface ------------------------------

function groupItem(
  id: string,
  overrides: Partial<TrackedItemCard> = {},
): TrackedItemCard {
  return { ...degraded, degraded_reason: null, title: id, id, ...overrides };
}

const grouping: TrackedGrouping = {
  boards: [
    { id: "b1", name: "Economy", created_at: "2026-07-01T00:00:00+00:00" },
    { id: "b2", name: "Tech", created_at: "2026-07-01T00:00:00+00:00" },
  ],
  modulesByBoard: {
    b1: [{ id: "m1", board_id: "b1", name: "Rates", created_at: "2026-07-01T00:00:00+00:00" }],
  },
};

describe("TrackedItemsSection grouped by board/module (M16.6)", () => {
  beforeEach(() => window.localStorage.clear());

  it("groups under board heads with module sub-heads, no-board last, order untouched", () => {
    const items = [
      groupItem("econ rates", { board_id: "b1", module_id: "m1" }),
      groupItem("tech one", { board_id: "b2" }),
      groupItem("orphan", { board_id: null }),
      groupItem("econ plain", { board_id: "b1" }),
    ];
    render(
      <LocaleProvider>
        <TrackedItemsSection items={items} grouping={grouping} />
      </LocaleProvider>,
    );
    // boards in API order, the no-board bucket honestly labeled and LAST
    const heads = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(heads).toEqual(["Economy", "Tech", "No board yet"]);
    const econ = screen.getByRole("region", { name: "Economy" });
    // the module name is a sub-head inside its board group
    expect(within(econ).getByRole("heading", { level: 4, name: "Rates" })).toBeInTheDocument();
    // incoming order is preserved WITHIN the group — grouping never re-sorts
    const econTitles = within(econ)
      .getAllByRole("link", { name: /econ/ })
      .map((l) => l.textContent);
    expect(econTitles).toEqual(["econ rates", "econ plain"]);
    expect(
      within(screen.getByRole("region", { name: "No board yet" })).getByRole("link", {
        name: "orphan",
      }),
    ).toBeInTheDocument();
  });

  it("shows per-group stats on demand (Digest): counts, sources, latest, tier spread", () => {
    const items = [
      groupItem("a", { board_id: "b1", domain: "sec.gov", tier: "T1", published: "2026-07-01T00:00:00+00:00" }),
      groupItem("b", { board_id: "b1", domain: "reuters.com", tier: "T2", published: "2026-07-03T00:00:00+00:00" }),
      groupItem("c", { board_id: "b1", domain: "sec.gov", tier: "T1", published: null }),
    ];
    render(
      <LocaleProvider>
        <TrackedItemsSection items={items} grouping={grouping} stats />
      </LocaleProvider>,
    );
    const econ = screen.getByRole("region", { name: "Economy" });
    // counts + distinct sources + latest + tier distribution, computed in code
    expect(within(econ).getByText(/items 3 · sources 2 · latest .+ · T1 ×2 · T2 ×1/)).toBeInTheDocument();
  });

  it("degrades to the flat list when no boards are known — items never hide", () => {
    render(
      <LocaleProvider>
        <TrackedItemsSection
          items={[groupItem("solo", { board_id: "b1" })]}
          grouping={{ boards: [], modulesByBoard: {} }}
        />
      </LocaleProvider>,
    );
    expect(screen.getByRole("link", { name: "solo" })).toBeInTheDocument();
    expect(screen.queryAllByRole("heading", { level: 3 })).toEqual([]);
  });
});

describe("trackedTitle follows the locale (2026-07-10)", () => {
  beforeEach(() => window.localStorage.clear());

  it("renders the translated title in zh and the original elsewhere", () => {
    const item: TrackedItemCard = {
      ...degraded,
      degraded_reason: null,
      enrichment: {
        summary_zh: "来源称。",
        summary_en: "The source says.",
        title_zh: "标题(中文)",
        title_en: "Title (English)",
        why_zh: null,
        why_en: null,
        entities: [],
        tags: [],
        limitations_zh: null,
        limitations_en: null,
      },
    };
    window.localStorage.setItem("daily.locale", "zh");
    render(
      <LocaleProvider>
        <TrackedItemLite item={item} />
      </LocaleProvider>,
    );
    expect(screen.getByRole("link", { name: "标题(中文)" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Title (English)" })).toBeNull();
  });

  it("degrades to the source's own title when no translation is cached", () => {
    window.localStorage.setItem("daily.locale", "zh");
    render(
      <LocaleProvider>
        <TrackedItemLite item={degraded} />
      </LocaleProvider>,
    );
    expect(
      screen.getByRole("link", { name: "SEC market-structure rules" }),
    ).toBeInTheDocument();
  });
});

