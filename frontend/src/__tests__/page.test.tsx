import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Home now renders the Today dashboard (TodayView fetches on mount) — mock the API so
// the page test never hits the network.
vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  adoptSourcePack: async () => ({ seeded: false, subscriptions: [] }),
  pollNow: async () => ({}),
  queryBoards: async () => [],
  queryModules: async () => [],
  queryDigest: async () => ({
    date: "2026-07-01",
    items: [],
    tracked: [
      {
        id: "ti1",
        board_id: null,
        module_id: null,
        url: "https://www.sec.gov/news/acme",
        title: "Acme posted record quarterly revenue.",
        domain: "sec.gov",
        tier: "T1",
        published: null,
        first_seen: "2026-07-01T00:00:00+00:00",
        status: "fetched",
        failure_kind: null,
        degraded_reason: null,
        summary: null,
        similar_count: 0,
      },
    ],
  }),
  querySubscriptions: async () => [
    {
      id: "s1",
      board_id: null,
      input_url: "https://www.sec.gov/news",
      feed_url: null,
      mode: "direct",
      interval_minutes: 60,
      last_polled: null,
      last_seen_item_key_for_display: null,
      consecutive_failures: 0,
      health: "ok",
      last_error: null,
      subscription_failure_kind: null,
    },
  ],
}));

import Home from "@/app/page";

describe("Home = Today dashboard", () => {
  it("leads with a Today dashboard of tracked items, with no check surface", async () => {
    render(<Home />);
    expect(screen.getByRole("heading", { name: "Today", level: 1 })).toBeInTheDocument();
    // the briefing renders what the sources published …
    expect(await screen.findByText("Acme posted record quarterly revenue.")).toBeInTheDocument();
    // … it is a dashboard, not a verify form; the check surface is retired (M16.1)
    expect(screen.queryByLabelText("Source URL")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Check information" })).toBeNull();
    expect(document.body.textContent).not.toMatch(/credibility|verdict|deep check/i);
  });

  it("keeps internal pipeline words off the first screen", async () => {
    const { container } = render(<Home />);
    await screen.findByText("Acme posted record quarterly revenue.");
    const text = container.textContent?.toLowerCase() ?? "";
    for (const word of [
      "k_eff",
      "independence",
      "stance matrix",
      "pipeline",
      "memoryitem",
      "credibility",
      "score",
    ]) {
      expect(text).not.toContain(word);
    }
  });
});
