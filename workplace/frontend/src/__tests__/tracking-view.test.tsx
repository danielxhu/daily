import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TrackingView } from "@/components/TrackingView";
import {
  createBoard,
  createSubscription,
  deleteSubscription,
  pollNow,
  queryBoards,
  querySubscriptions,
} from "@/lib/api";
import type { PollReport } from "@/lib/api";
import { buildMockBoards, buildMockSubscriptions } from "@/mocks/fixtures";
import type { Subscription } from "@/types/contract";

const EMPTY_POLL: PollReport = {
  run_id: "r1",
  polled: 0,
  new_items: 0,
  system_anomaly: false,
  subscriptions: [],
};

function setup(
  overrides: {
    subscriptionsFn?: typeof querySubscriptions;
    createFn?: typeof createSubscription;
    deleteFn?: typeof deleteSubscription;
    pollFn?: typeof pollNow;
    createBoardFn?: typeof createBoard;
  } = {},
) {
  const subscriptionsFn = vi.fn(overrides.subscriptionsFn ?? (async () => buildMockSubscriptions()));
  const createFn = vi.fn(
    overrides.createFn ??
      (async (sub: { input_url: string; mode: string; board_id?: string | null }) =>
        ({
          id: "sub_new",
          board_id: sub.board_id ?? null,
          input_url: sub.input_url,
          feed_url: null,
          mode: sub.mode,
          interval_minutes: 60,
          last_polled: null,
          last_seen_item_key_for_display: null,
          consecutive_failures: 0,
          health: "ok",
          last_error: null,
          subscription_failure_kind: null,
        }) as Subscription),
  );
  const deleteFn = vi.fn(overrides.deleteFn ?? (async () => undefined));
  const pollFn = vi.fn(overrides.pollFn ?? (async () => EMPTY_POLL));
  const boardsFn = vi.fn(async () => buildMockBoards());
  const createBoardFn = vi.fn(overrides.createBoardFn ?? (async () => buildMockBoards()[0]));
  render(
    <TrackingView
      subscriptionsFn={subscriptionsFn as unknown as typeof querySubscriptions}
      createFn={createFn as unknown as typeof createSubscription}
      deleteFn={deleteFn as unknown as typeof deleteSubscription}
      createBoardFn={createBoardFn as unknown as typeof createBoard}
      pollFn={pollFn as unknown as typeof pollNow}
      boardsFn={boardsFn as unknown as typeof queryBoards}
    />,
  );
  return { subscriptionsFn, createFn, deleteFn, pollFn };
}

describe("TrackingView", () => {
  it("shows a loading state while subscriptions are being fetched", () => {
    setup({
      subscriptionsFn: (() =>
        new Promise<never>(() => {})) as unknown as typeof querySubscriptions,
    });
    expect(screen.getByText("Loading your sources…")).toBeInTheDocument();
  });

  it("shows the NFR-6 honesty disclosure", async () => {
    setup();
    expect(screen.getByText(/not real-time push/)).toBeInTheDocument();
    expect(screen.getByText(/only while this machine is on/)).toBeInTheDocument();
    await screen.findByRole("list", { name: "Your sources" }); // let the load settle
  });

  it("lists subscriptions with mode and health, and shows a next action (not just a log)", async () => {
    setup();
    const list = await screen.findByRole("list", { name: "Your sources" });
    expect(
      within(list).getByText("https://www.federalreserve.gov/feeds/press_all.xml"),
    ).toBeInTheDocument();
    expect(within(list).getByText("ok")).toBeInTheDocument();
    expect(within(list).getByText("unhealthy")).toBeInTheDocument();
    // the mode is shown in user language — never the raw enum (the mock has a
    // `homepage_diff` source, which must read as "Watch homepage for changes")
    expect(within(list).getByText("Watch homepage for changes")).toBeInTheDocument();
    expect(within(list).queryByText("homepage_diff")).toBeNull();
    // §6.6: the unhealthy source shows the user a NEXT STEP …
    expect(within(list).getByText(/Replace or remove this source/)).toBeInTheDocument();
    // … with the raw error kept only as secondary detail
    expect(within(list).getByText(/Last error: 404 Not Found/)).toBeInTheDocument();
  });

  it("adds a source with the chosen mode, sending the raw enum value", async () => {
    const { createFn } = setup();
    await screen.findByRole("list", { name: "Your sources" });
    fireEvent.change(screen.getByLabelText("Source URL"), {
      target: { value: "https://x.example/feed.xml" },
    });
    // the option reads in user language …
    expect(
      screen.getByRole("option", { name: "Watch homepage for changes" }),
    ).toBeInTheDocument();
    // … but selecting it still submits the backend enum value
    fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "platform" } });
    fireEvent.click(screen.getByRole("button", { name: "Add source" }));
    await waitFor(() =>
      expect(createFn).toHaveBeenCalledWith({
        input_url: "https://x.example/feed.xml",
        mode: "platform",
        board_id: null,
      }),
    );
    expect(await screen.findByText("https://x.example/feed.xml")).toBeInTheDocument();
  });

  it("groups sources by topic board and offers preset boards in the add form (M12.1)", async () => {
    const { createFn } = setup();
    const list = await screen.findByRole("list", { name: "Your sources" });
    // board group headers: the finance sub under its board, the boardless one under
    // the ungrouped bucket
    expect(within(list).getByText("Finance")).toBeInTheDocument();
    expect(within(list).getByText("No board")).toBeInTheDocument();
    // the add form offers the preset topic boards (政治/经济/科技)
    const select = screen.getByLabelText("Board (optional)");
    expect(within(select).getByRole("option", { name: "政治" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "经济" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "科技" })).toBeInTheDocument();
    // choosing a board submits its id
    fireEvent.change(screen.getByLabelText("Source URL"), {
      target: { value: "https://politics.example/feed.xml" },
    });
    fireEvent.change(select, { target: { value: "b_politics" } });
    fireEvent.click(screen.getByRole("button", { name: "Add source" }));
    await waitFor(() =>
      expect(createFn).toHaveBeenCalledWith({
        input_url: "https://politics.example/feed.xml",
        mode: "direct",
        board_id: "b_politics",
      }),
    );
  });

  it("blocks an empty URL without calling the API", async () => {
    const { createFn } = setup();
    await screen.findByRole("list", { name: "Your sources" });
    fireEvent.click(screen.getByRole("button", { name: "Add source" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a feed, homepage, or channel URL.");
    expect(createFn).not.toHaveBeenCalled();
  });

  it("removes a subscription", async () => {
    const { deleteFn } = setup();
    await screen.findByRole("list", { name: "Your sources" });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Remove https://www.federalreserve.gov/feeds/press_all.xml",
      }),
    );
    await waitFor(() => expect(deleteFn).toHaveBeenCalledWith("sub_fed"));
    expect(
      screen.queryByText("https://www.federalreserve.gov/feeds/press_all.xml"),
    ).not.toBeInTheDocument();
  });

  it("surfaces an API error", async () => {
    setup({
      subscriptionsFn: (async () => {
        throw new Error("boom");
      }) as unknown as typeof querySubscriptions,
    });
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Could not load your sources."),
    );
  });

  it("polls now and shows a summary, then refreshes the list", async () => {
    const report: PollReport = {
      run_id: "r2",
      polled: 2,
      new_items: 3,
      system_anomaly: false,
      subscriptions: [],
    };
    const { pollFn, subscriptionsFn } = setup({
      pollFn: (async () => report) as unknown as typeof pollNow,
    });
    await screen.findByRole("list", { name: "Your sources" });
    expect(subscriptionsFn).toHaveBeenCalledTimes(1); // initial load only

    fireEvent.click(screen.getByRole("button", { name: "Check for new items" }));
    await waitFor(() => expect(pollFn).toHaveBeenCalledTimes(1));
    // M16.1: the summary counts sources and items only — verification outcomes
    // (written facts / corroboration) left the surface with the check retirement
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Checked 2 sources.");
    expect(status).not.toHaveTextContent(/verified|corroboration/);
    // the list is re-fetched so updated health/last-checked shows after the check
    await waitFor(() => expect(subscriptionsFn).toHaveBeenCalledTimes(2));
  });

  it("surfaces per-item ingestion failures with a typed reason (M13.1, paste path retired by M16.1)", async () => {
    // the beta P0-1 case: the feed polls fine, every article page is bot-blocked —
    // this must never read as "all ok with zero results"
    const report: PollReport = {
      run_id: "r3",
      polled: 1,
      new_items: 3,
      system_anomaly: false,
      subscriptions: [
        {
          subscription_id: "sub_fed",
          input_url: "https://www.federalreserve.gov/feeds/press_all.xml",
          ok: false,
          new_items: 3,
          items_ok: 0,
          items_failed: 3,
          item_failures: [
            {
              url: "https://www.federalreserve.gov/newsevents/a.htm",
              kind: "anti_bot",
              next_action: "paste the text + a source label/domain",
            },
          ],
          failure_kind: "items_unfetchable",
          next_action: "Paste the article text on the Check page instead.",
          error: "3/3 new items failed ingestion: anti_bot ×3",
        },
      ],
    };
    setup({ pollFn: (async () => report) as unknown as typeof pollNow });
    await screen.findByRole("list", { name: "Your sources" });
    fireEvent.click(screen.getByRole("button", { name: "Check for new items" }));

    // the summary counts the failed items honestly
    expect(await screen.findByRole("status")).toHaveTextContent(
      "3 items couldn't be fetched (below)",
    );
    // the flagged source shows the typed reason and the counts; the /check paste
    // link left with the check retirement (M16.1) — no dead route is offered
    const flagged = screen.getByRole("list", { name: "Sources this check flagged" });
    expect(flagged).toHaveTextContent("https://www.federalreserve.gov/feeds/press_all.xml");
    expect(flagged).toHaveTextContent(/articles themselves can't be fetched/);
    expect(flagged).toHaveTextContent("3 of 3 new items couldn't be fetched");
    expect(within(flagged).queryByRole("link")).toBeNull();
  });

  it("says so when a first check skipped the older backlog (M13.4)", async () => {
    const report: PollReport = {
      run_id: "r4",
      polled: 1,
      new_items: 5,
      system_anomaly: false,
      subscriptions: [
        {
          subscription_id: "sub_fed",
          input_url: "https://www.federalreserve.gov/feeds/press_all.xml",
          ok: true,
          new_items: 5,
          items_ok: 5,
          items_failed: 0,
          item_failures: [],
          backlog_skipped: 15, // first check: latest 5 of 20, the rest skipped for good
        },
      ],
    };
    setup({ pollFn: (async () => report) as unknown as typeof pollNow });
    await screen.findByRole("list", { name: "Your sources" });
    fireEvent.click(screen.getByRole("button", { name: "Check for new items" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "15 older items skipped (a first check picks up the latest only; later checks are incremental)",
    );
  });

  it("says so when a first check deferred audio/video transcription (M14.5)", async () => {
    const report: PollReport = {
      run_id: "r5",
      polled: 1,
      new_items: 3,
      system_anomaly: false,
      subscriptions: [
        {
          subscription_id: "sub_pod",
          input_url: "https://feeds.example.com/podcast.xml",
          ok: true, // deferral is delayed processing, never a failure
          new_items: 3,
          items_ok: 1,
          items_failed: 0,
          item_failures: [],
          items_deferred: 2, // first check: whisper items wait for the next check
        },
      ],
    };
    setup({ pollFn: (async () => report) as unknown as typeof pollNow });
    await screen.findByRole("list", { name: "Your sources" });
    fireEvent.click(screen.getByRole("button", { name: "Check for new items" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "2 audio/video items awaiting on-demand transcription (open the item → Fetch & summarize)",
    );
    // deferral is not a failure: no flagged-sources block appears
    expect(screen.queryByRole("list", { name: "Sources this check flagged" })).toBeNull();
  });

  it("shows no flagged-sources block when a check comes back clean (M13.1)", async () => {
    setup(); // EMPTY_POLL: nothing failed
    await screen.findByRole("list", { name: "Your sources" });
    fireEvent.click(screen.getByRole("button", { name: "Check for new items" }));
    await screen.findByRole("status");
    expect(screen.queryByRole("list", { name: "Sources this check flagged" })).toBeNull();
  });

  it("surfaces a poll error without crashing", async () => {
    const { pollFn } = setup({
      pollFn: (async () => {
        throw new Error("nope");
      }) as unknown as typeof pollNow,
    });
    await screen.findByRole("list", { name: "Your sources" });
    fireEvent.click(screen.getByRole("button", { name: "Check for new items" }));
    await waitFor(() => expect(pollFn).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("alert")).toHaveTextContent("Could not check your sources.");
  });

  it("says a source poll is already running on 409 instead of an error (M14.4)", async () => {
    const { ApiError } = await import("@/lib/api");
    setup({
      pollFn: (async () => {
        throw new ApiError(409, "a check is already running");
      }) as unknown as typeof pollNow,
    });
    await screen.findByRole("list", { name: "Your sources" });
    fireEvent.click(screen.getByRole("button", { name: "Check for new items" }));
    // informational status, not a red alert
    expect(await screen.findByRole("status")).toHaveTextContent(
      "A source poll is already running — new items keep landing as it progresses.",
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

// owner 2026-07-13: boards are created HERE, where sources are added
describe("TrackingView creates boards inline", () => {
  it("creates a board from the add-source form and selects it", async () => {
    const createBoardFn = vi.fn(async (name: string) => ({
      id: `b_${name.toLowerCase()}`,
      name,
      created_at: "2026-07-13T00:00:00+00:00",
    }));
    setup({ createBoardFn: createBoardFn as unknown as typeof createBoard });
    await screen.findByLabelText("Board (optional)");
    fireEvent.change(screen.getByLabelText("New board name"), { target: { value: "Macro" } });
    fireEvent.click(screen.getByRole("button", { name: "Create board" }));
    await waitFor(() => expect(createBoardFn).toHaveBeenCalledWith("Macro"));
    // the fresh board is selected in the dropdown, ready for the source
    expect(screen.getByLabelText("Board (optional)")).toHaveValue("b_macro");
  });

  it("an empty name is a no-op — no API call", async () => {
    const createBoardFn = vi.fn();
    setup({ createBoardFn: createBoardFn as unknown as typeof createBoard });
    await screen.findByLabelText("Board (optional)");
    fireEvent.click(screen.getByRole("button", { name: "Create board" }));
    expect(createBoardFn).not.toHaveBeenCalled();
  });
});

