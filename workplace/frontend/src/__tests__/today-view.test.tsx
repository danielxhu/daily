import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TodayView } from "@/components/TodayView";
import type { queryBoards, queryModules } from "@/lib/api";
import {
  adoptSourcePack,
  pollNow,
  queryDigest,
  querySubscriptions,
} from "@/lib/api";
import type { DailyDigest, Subscription, TrackedItemCard } from "@/types/contract";

function tracked(overrides: Partial<TrackedItemCard> & { id: string }): TrackedItemCard {
  return {
    board_id: null,
    module_id: null,
    url: "https://www.sec.gov/news/x",
    title: "SEC statement on rulemaking",
    domain: "sec.gov",
    tier: "T1",
    published: "2026-07-01T07:00:00+00:00",
    first_seen: "2026-07-01T07:10:00+00:00",
    status: "fetched",
    failure_kind: null,
    degraded_reason: null,
    summary: null,
    similar_count: 0,
    ...overrides,
  };
}

function digest(items: TrackedItemCard[]): DailyDigest {
  // `items` (the dormant verified-fact list) stays empty: the UI must not need it
  return { date: "2026-07-01", generated_at: "2026-07-01T00:00:00Z", tracked: items };
}

function sub(id: string, url: string, health: "ok" | "unhealthy"): Subscription {
  return {
    id,
    input_url: url,
    feed_url: null,
    mode: "direct",
    last_polled: null,
    last_seen_item_key_for_display: null,
    health,
  };
}

function setup(d: DailyDigest, subs: Subscription[]) {
  render(
    <TodayView
      digestFn={vi.fn(async () => d) as unknown as typeof queryDigest}
      subscriptionsFn={vi.fn(async () => subs) as unknown as typeof querySubscriptions}
    />,
  );
}

/** A true cold start (no sources, empty digest) with injected adopt/poll (M14.1). */
function setupEmpty(adoptFn: typeof adoptSourcePack, pollFn: typeof pollNow) {
  render(
    <TodayView
      digestFn={vi.fn(async () => digest([])) as unknown as typeof queryDigest}
      subscriptionsFn={
        vi.fn(async () => [] as Subscription[]) as unknown as typeof querySubscriptions
      }
      adoptFn={adoptFn}
      pollFn={pollFn}
    />,
  );
}

// M16.1 (check retirement): Today's briefing IS the tracked-items channel. The
// verified-fact briefing, verdict-changed attention rows, credibility scores and
// the deep-check entry are all dormant — no check language anywhere.

describe("TodayView (dashboard)", () => {
  it("shows the tracked briefing, needs-attention, and source status — no check surface", async () => {
    setup(
      digest([
        tracked({
          id: "ti1",
          summary: "The SEC says its rulemaking enters a comment period.",
        }),
      ]),
      [sub("s1", "https://sec.gov/x", "ok"), sub("s2", "https://bad.example/feed", "unhealthy")],
    );

    // the briefing surfaces what the sources published; the legacy summary is
    // never rendered (M16.1) — a neutral pending state shows instead
    const briefing = await screen.findByRole("region", { name: "New from your sources" });
    // M16.4: the title deep-links to the item's detail page
    expect(
      within(briefing).getByRole("link", { name: "SEC statement on rulemaking" }),
    ).toHaveAttribute("href", "/items/ti1");
    expect(within(briefing).queryByText(/comment period/)).toBeNull();
    expect(within(briefing).getByText("AI summary pending")).toBeInTheDocument();

    // needs attention = the unhealthy source (verdict rows are dormant)
    const attention = screen.getByRole("region", { name: "Needs attention" });
    expect(attention).toHaveTextContent("A source needs a look");
    expect(attention).toHaveTextContent("https://bad.example/feed");

    // the check surface is retired: no Check entry, no score language
    expect(screen.queryByRole("link", { name: "Check information" })).toBeNull();
    expect(document.body.textContent).not.toMatch(/credibility|verdict|deep check|\/100/i);

    // source status counts, honestly
    const sources = screen.getByRole("region", { name: "Your sources" });
    expect(sources).toHaveTextContent("Watching 2 sources");
    expect(sources).toHaveTextContent("need a look");
  });

  it("auto-adopts the starter pack and runs a first poll on a cold start (M14.1)", async () => {
    const seededSub = sub("s_new", "https://www.sec.gov/news/pressreleases.rss", "ok");
    const filled = digest([
      tracked({ id: "ti1", title: "The SEC adopted new market-structure rules." }),
    ]);
    // cold start: first load sees nothing; after seed + poll, content exists
    const subscriptionsFn = vi
      .fn<() => Promise<Subscription[]>>()
      .mockResolvedValueOnce([])
      .mockResolvedValue([seededSub]);
    const digestFn = vi
      .fn<() => Promise<DailyDigest>>()
      .mockResolvedValueOnce(digest([]))
      .mockResolvedValue(filled);
    const adoptFn = vi.fn(async () => ({ seeded: true, subscriptions: [seededSub] }));
    let resolvePoll!: (v: unknown) => void;
    const pollFn = vi.fn(() => new Promise((r) => (resolvePoll = r)));
    render(
      <TodayView
        digestFn={digestFn as unknown as typeof queryDigest}
        subscriptionsFn={subscriptionsFn as unknown as typeof querySubscriptions}
        adoptFn={adoptFn as unknown as typeof adoptSourcePack}
        pollFn={pollFn as unknown as typeof pollNow}
      />,
    );

    // while the first poll runs, the user is told what is happening (honestly:
    // sources were loaded FOR them, the first poll is capped, trimming is theirs)
    expect(await screen.findByRole("status")).toHaveTextContent(
      /Loaded the recommended sources for you/,
    );
    expect(adoptFn).toHaveBeenCalledTimes(1);
    resolvePoll({});
    // after the poll: the briefing shows real content and the sources are in
    expect(
      await screen.findByText("The SEC adopted new market-structure rules."),
    ).toBeInTheDocument();
    expect(pollFn).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("region", { name: "Your sources" })).toHaveTextContent(
      "Watching 1 source",
    );
  });

  it("survives the interval refresh landing subscriptions mid-poll (M14.4 review fix)", async () => {
    // the blocker scenario: poll runs >15s; the interval refresh writes subs
    // ([] → 1), which re-runs the seeding effect — the flow must NOT be aborted
    // by its own cleanup, or "polling…" sticks forever and the final refresh dies
    vi.useFakeTimers();
    try {
      const seededSub = sub("s_new", "https://www.sec.gov/news/pressreleases.rss", "ok");
      const filled = digest([
        tracked({ id: "ti1", title: "The SEC adopted new market-structure rules." }),
      ]);
      const subscriptionsFn = vi
        .fn<() => Promise<Subscription[]>>()
        .mockResolvedValueOnce([]) // initial load: a true cold start
        .mockResolvedValue([seededSub]); // every refresh thereafter
      const digestFn = vi
        .fn<() => Promise<DailyDigest>>()
        .mockResolvedValueOnce(digest([]))
        .mockResolvedValue(filled);
      const adoptFn = vi.fn(async () => ({ seeded: true, subscriptions: [seededSub] }));
      let resolvePoll!: (v: unknown) => void;
      const pollFn = vi.fn(() => new Promise((r) => (resolvePoll = r)));
      render(
        <TodayView
          digestFn={digestFn as unknown as typeof queryDigest}
          subscriptionsFn={subscriptionsFn as unknown as typeof querySubscriptions}
          adoptFn={adoptFn as unknown as typeof adoptSourcePack}
          pollFn={pollFn as unknown as typeof pollNow}
        />,
      );

      // mount effects settle: adopt fired, seeding status up
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByRole("status")).toHaveTextContent(
        /Loaded the recommended sources for you/,
      );
      const digestCallsBefore = digestFn.mock.calls.length;

      // +15s: the interval refresh fires and lands NON-EMPTY subs — the seeding
      // flow must survive the effect re-run this causes
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      expect(digestFn.mock.calls.length).toBeGreaterThan(digestCallsBefore);
      expect(screen.getByRole("status")).toHaveTextContent(
        /Loaded the recommended sources for you/, // still honestly polling
      );
      expect(adoptFn).toHaveBeenCalledTimes(1); // never re-adopted

      // the poll completes → final refresh runs → the seeding status CLEARS
      resolvePoll({});
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.queryByRole("status")).toBeNull();
      expect(
        screen.getByText("The SEC adopted new market-structure rules."),
      ).toBeInTheDocument();
      expect(pollFn).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps a deliberately emptied source list empty — no forced refill (M14.1)", async () => {
    // the backend flag says seeding already happened: the user deleted everything
    const adoptFn = vi.fn(async () => ({ seeded: false, subscriptions: [] }));
    const pollFn = vi.fn();
    setupEmpty(adoptFn as unknown as typeof adoptSourcePack, pollFn as unknown as typeof pollNow);
    // the normal empty state renders; no poll is triggered, nothing is re-added
    expect(await screen.findByText(/Nothing new from your sources yet/)).toBeInTheDocument();
    await waitFor(() => expect(adoptFn).toHaveBeenCalledTimes(1));
    expect(pollFn).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("flags a first item-level failure even while health is still 'ok' (M13.1)", async () => {
    // beta P0-1: the first items_unfetchable failure writes kind + last_error but
    // health stays "ok" until the §6.6 threshold — Today must NOT read that as
    // "all healthy" while the Sources page is already showing a typed failure.
    const flagged: Subscription = {
      ...sub("s1", "https://www.federalreserve.gov/feeds/press_all.xml", "ok"),
      subscription_failure_kind: "items_unfetchable",
      last_error: "3/3 new items failed ingestion: anti_bot ×3",
    };
    setup(digest([tracked({ id: "ti1" })]), [flagged]);
    const attention = await screen.findByRole("region", { name: "Needs attention" });
    expect(attention).toHaveTextContent("A source needs a look");
    expect(attention).toHaveTextContent("https://www.federalreserve.gov/feeds/press_all.xml");
    // the row links through to Sources where the typed reason lives
    expect(within(attention).getByRole("link", { name: "open Sources" })).toHaveAttribute(
      "href",
      "/tracking",
    );
    const sources = screen.getByRole("region", { name: "Your sources" });
    expect(sources).toHaveTextContent("need a look");
    expect(sources).not.toHaveTextContent("all healthy");
  });

  it("is calm when nothing needs attention", async () => {
    setup(digest([tracked({ id: "ti1" })]), [sub("s1", "https://sec.gov/x", "ok")]);
    const attention = await screen.findByRole("region", { name: "Needs attention" });
    expect(attention).toHaveTextContent("Nothing needs your attention right now.");
    expect(screen.getByRole("region", { name: "Your sources" })).toHaveTextContent("all healthy");
  });
});

describe("TodayView tracked items (M15.1a → M16.1 expression)", () => {
  it("shows tracked items with lite signals — degraded ones stay visible, no scores", async () => {
    setup(
      digest([
        tracked({
          id: "ti1",
          // the ENTIRE deep pipeline failed for this item — it must still show
          degraded_reason: "claim extraction failed — a later pass can retry",
          summary: "The SEC says its rulemaking enters a comment period.",
          similar_count: 3,
        }),
      ]),
      [sub("s1", "https://sec.gov/x", "ok")],
    );
    const section = await screen.findByRole("region", { name: "New from your sources" });
    // the item is visible with its lite signals (detail link, domain, tier)
    expect(within(section).getByRole("link", { name: "SEC statement on rulemaking" })).toHaveAttribute(
      "href",
      "/items/ti1",
    );
    expect(within(section).getByRole("link", { name: "original ↗" })).toHaveAttribute(
      "href",
      "https://www.sec.gov/news/x",
    );
    expect(section).toHaveTextContent("sec.gov");
    expect(section).toHaveTextContent("T1 · primary/official");
    // degradation is said in neutral terms, not hidden — and not in check language
    expect(section).toHaveTextContent("fetched · processing didn't finish — will retry");
    // the legacy single-language summary is never rendered (M16.1)
    expect(within(section).queryByText(/rulemaking enters a comment period/)).toBeNull();
    expect(within(section).getByText("AI summary pending")).toBeInTheDocument();
    // the dup/repost hint is phrased as an echo, never as corroboration
    expect(within(section).getByText("similar item from 3 other sources")).toBeInTheDocument();
    // the check surface is retired: no deep-check badge/button, no fabricated score
    expect(within(section).queryByText(/deep-checked/i)).toBeNull();
    expect(within(section).queryByRole("button")).toBeNull();
    expect(within(section).queryByText(/confidence · \d+\/100/)).toBeNull();
  });

  it("shows typed statuses for failed and deferred items — visible, never vanished", async () => {
    setup(
      digest([
        tracked({
          id: "ti2",
          url: "https://blocked.example.com/a",
          title: null,
          domain: "blocked.example.com",
          tier: "T2",
          published: null,
          status: "failed",
          failure_kind: "anti_bot",
        }),
        tracked({
          id: "ti3",
          url: "https://podcasts.example.com/ep1",
          title: "Episode 1",
          domain: "podcasts.example.com",
          tier: "T2",
          published: null,
          status: "deferred",
          failure_kind: "transcription_deferred",
        }),
      ]),
      [sub("s1", "https://sec.gov/x", "ok")],
    );
    const section = await screen.findByRole("region", { name: "New from your sources" });
    expect(section).toHaveTextContent("blocked by anti-bot");
    // deferred items stay visible but carry NO stale "click to fetch" hint —
    // the background worker owns transcription (owner 2026-07-20 "去掉")
    expect(section).toHaveTextContent("Episode 1");
    expect(within(section).queryByText(/transcription on demand/)).toBeNull();
    // no echo → the hint does not appear (nothing fabricated)
    expect(within(section).queryByText(/similar item from/)).toBeNull();
  });

  it("shows the empty state inside the briefing when the channel is empty", async () => {
    setup(digest([]), [sub("s1", "https://sec.gov/x", "ok")]);
    const section = await screen.findByRole("region", { name: "New from your sources" });
    expect(within(section).getByText(/Nothing new from your sources yet/)).toBeInTheDocument();
    expect(within(section).getByRole("link", { name: "Sources" })).toHaveAttribute(
      "href",
      "/tracking",
    );
  });
});

// --- Today header + the AIHOT-style timeline with board tabs (2026-07-10) ------

describe("Today header and timeline briefing", () => {
  function renderTimeline(subs: Subscription[], items?: TrackedItemCard[]) {
    const boardsFn = vi.fn(async () => [
      { id: "b1", name: "Economy", created_at: "2026-07-01T00:00:00+00:00" },
      { id: "b2", name: "Tech", created_at: "2026-07-01T00:00:00+00:00" },
    ]);
    const modulesFn = vi.fn(async () => []);
    render(
      <TodayView
        digestFn={
          vi.fn(async () =>
            digest(
              items ?? [
                tracked({ id: "t1", board_id: "b1", title: "econ item" }),
                tracked({
                  id: "t2",
                  board_id: "b2",
                  title: "tech item",
                  published: "2026-07-02T09:00:00+00:00",
                }),
              ],
            ),
          ) as unknown as typeof queryDigest
        }
        subscriptionsFn={vi.fn(async () => subs) as unknown as typeof querySubscriptions}
        boardsFn={boardsFn as unknown as typeof queryBoards}
        modulesFn={modulesFn as unknown as typeof queryModules}
      />,
    );
  }

  it("shows the date header with the latest poll and the honest non-real-time note", async () => {
    renderTimeline([
      { ...sub("s1", "https://a.example/feed", "ok"), last_polled: "2026-07-08T06:00:00+00:00" },
    ]);
    const head = await screen.findByLabelText("Today overview");
    expect(within(head).getByText(/Last poll .*not real-time/)).toBeInTheDocument();
  });

  it("says honestly that no poll has run yet on a fresh setup", async () => {
    renderTimeline([sub("s1", "https://a.example/feed", "ok")]);
    const head = await screen.findByLabelText("Today overview");
    expect(within(head).getByText(/No poll has run yet/)).toBeInTheDocument();
  });

  it("renders a chronological timeline: day headers, time rail, newest first", async () => {
    renderTimeline([sub("s1", "https://a.example/feed", "ok")]);
    // both items render under their day's header, newest day first
    await screen.findByRole("link", { name: "econ item" });
    const titles = screen
      .getAllByRole("link", { name: /item$/ })
      .map((l) => l.textContent);
    expect(titles).toEqual(["tech item", "econ item"]); // 07-02 before 07-01
    // day headers exist (locale date strings) as level-3 headings
    expect(screen.getAllByRole("heading", { level: 3 }).length).toBeGreaterThanOrEqual(2);
  });

  it("filters the timeline by board via the tabs — All shows everything again", async () => {
    renderTimeline([sub("s1", "https://a.example/feed", "ok")]);
    const tabs = await screen.findByRole("group", { name: "Board filter" });
    fireEvent.click(within(tabs).getByRole("button", { name: "Economy" }));
    expect(screen.getByRole("link", { name: "econ item" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "tech item" })).toBeNull();
    fireEvent.click(within(tabs).getByRole("button", { name: "All" }));
    expect(screen.getByRole("link", { name: "tech item" })).toBeInTheDocument();
  });

  it("an empty board filter says so instead of a blank page", async () => {
    renderTimeline(
      [sub("s1", "https://a.example/feed", "ok")],
      [tracked({ id: "t1", board_id: "b1", title: "econ item" })],
    );
    const tabs = await screen.findByRole("group", { name: "Board filter" });
    fireEvent.click(within(tabs).getByRole("button", { name: "Tech" }));
    expect(screen.getByText(/Nothing from this board/)).toBeInTheDocument();
  });
});
