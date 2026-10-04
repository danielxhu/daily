import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TraceView } from "@/components/TraceView";
import { queryRuns } from "@/lib/api";
import { buildMockRuns } from "@/mocks/fixtures";

function setup(runsFn?: typeof queryRuns) {
  const fn = vi.fn(runsFn ?? (async () => buildMockRuns()));
  render(<TraceView runsFn={fn as unknown as typeof queryRuns} />);
  return { fn };
}

describe("TraceView", () => {
  it("shows a loading state while runs are being fetched", () => {
    setup((() => new Promise<never>(() => {})) as unknown as typeof queryRuns);
    expect(screen.getByText("Loading runs…")).toBeInTheDocument();
  });

  it("lists poll runs and makes a failed run inspectable", async () => {
    setup();
    const list = await screen.findByRole("list", { name: "Pipeline runs" });
    expect(within(list).getAllByText("poll").length).toBeGreaterThanOrEqual(2);
    // the failed run's typed per-item summary is visible — you can see where
    // it got stuck (anti_bot on every article)
    expect(
      within(list).getByText(/3\/3 new items failed ingestion: anti_bot ×3/),
    ).toBeInTheDocument();
    // the failed fetch's typed kind rides as the fallback marker
    expect(within(list).getAllByText(/anti_bot/).length).toBeGreaterThanOrEqual(1);
  });

  it("marks a run with any failed step as failed overall", async () => {
    setup();
    await screen.findByRole("list", { name: "Pipeline runs" });
    expect(screen.getAllByText("failed").length).toBeGreaterThanOrEqual(1);
    // the clean poll run is ok
    expect(screen.getAllByText("ok").length).toBeGreaterThanOrEqual(1);
  });

  it("shows an empty state", async () => {
    setup((async () => []) as unknown as typeof queryRuns);
    await waitFor(() =>
      expect(screen.getByText("No pipeline runs recorded yet.")).toBeInTheDocument(),
    );
  });

  it("surfaces an API error", async () => {
    setup(
      (async () => {
        throw new Error("boom");
      }) as unknown as typeof queryRuns,
    );
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Could not load runs."),
    );
  });
});
