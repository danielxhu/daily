import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeView } from "@/components/KnowledgeView";
import { answerKnowledge, searchKnowledge } from "@/lib/api";
import type { KnowledgeNote } from "@/types/contract";

const quietAnswerFn = vi.fn(async () => ({
  answer: "unused",
  based_on: 1,
})) as unknown as typeof answerKnowledge;

function savedNote(
  content: string,
  kind: "saved_check" | "user_note" = "saved_check",
): KnowledgeNote {
  return {
    id: `n_${kind}_${content.length}`,
    board_id: "b_economy",
    kind,
    content,
    citations: [],
    is_synthesized: false,
    regenerable: false,
    created_at: "2026-07-06T00:00:00+00:00",
  };
}

function ask(question: string) {
  fireEvent.change(screen.getByLabelText("Ask daily"), { target: { value: question } });
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
}

// M16.1 (check retirement): the Knowledge search surface renders tracked items +
// the user's saved notes only. The verified-fact layer is dormant — even when
// the API still returns it, the UI must not render facts or scores.
// M16.2: search never produces an answer by itself; the AI answer is an explicit
// per-turn "Generate AI answer" action grounded only in the saved notes.

describe("KnowledgeView (search what your sources published + what you saved)", () => {
  it("returns the user's saved notes — saved checks AND ordinary notes (M16.2)", async () => {
    const askFn = vi.fn(async () => ({
      facts: [],
      saved: [
        savedNote("Fed approved the merger (federalreserve.gov)."),
        savedNote("merger follow-up: watch the July filing", "user_note"),
      ],
      answer: null,
    }));
    render(<KnowledgeView askFn={askFn as unknown as typeof searchKnowledge} />);
    ask("fed merger");

    await waitFor(() => expect(askFn).toHaveBeenCalledWith("fed merger"));
    const saved = await screen.findByRole("list", { name: "Your saved notes" });
    // M16.7: the badge is kind-aware — a saved check and the user's own note
    expect(within(saved).getByText("Saved by you")).toBeInTheDocument();
    expect(within(saved).getByText("Your note")).toBeInTheDocument();
    expect(
      within(saved).getByText("Fed approved the merger (federalreserve.gov)."),
    ).toBeInTheDocument();
    // M16.2 review: the user's ordinary notes surface in the same labeled region
    expect(
      within(saved).getByText("merger follow-up: watch the July filing"),
    ).toBeInTheDocument();
    // a saved-only result is NOT the nothing-matched empty state
    expect(screen.queryByText(/Nothing in your knowledge base matches/)).toBeNull();
  });

  it("says so when nothing matches, guiding to Sources and never to /check", async () => {
    render(
      <KnowledgeView
        askFn={
          vi.fn(async () => ({ facts: [], saved: [], answer: null })) as unknown as typeof searchKnowledge
        }
      />,
    );
    ask("something obscure");
    expect(
      await screen.findByText(/Nothing in your knowledge base matches that yet/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sources" })).toHaveAttribute("href", "/tracking");
    for (const link of screen.queryAllByRole("link")) {
      expect(link.getAttribute("href")).not.toBe("/check");
      expect(link.getAttribute("href")).not.toBe("/memory");
    }
  });

  it("never renders the dormant layers, even when the API still returns them (M16.1)", async () => {
    // the backend contract keeps `facts`/`answer` for compatibility — the UI
    // must ignore both; no score, no verified framing, no answer block
    const askFn = vi.fn(async () => ({
      facts: [
        {
          claim_id: "c1",
          canonical_text: "Rates were held steady.",
          version: 1,
          sources: [],
          verdict: { credibility: 82 },
        },
      ],
      saved: [savedNote("My own note about rates.")],
      answer: "Rates were held steady, per the verified fact below.",
    }));
    render(
      <KnowledgeView
        askFn={askFn as unknown as typeof searchKnowledge}
        answerFn={quietAnswerFn}
      />,
    );
    ask("what did the Fed do?");

    await screen.findByRole("list", { name: "Your saved notes" });
    expect(screen.queryByText("Rates were held steady.")).toBeNull();
    expect(screen.queryByText("AI answer")).toBeNull();
    expect(screen.queryByText(/per the verified fact below/)).toBeNull();
    expect(document.body.textContent).not.toMatch(/credibility|\/100|verified/i);
  });
});

describe("KnowledgeView on-demand AI answer (M16.2)", () => {
  const searchWithNote = vi.fn(async () => ({
    facts: [],
    saved: [savedNote("Fed approved the merger (federalreserve.gov).")],
    answer: null,
  })) as unknown as typeof searchKnowledge;

  it("search alone never calls the answer endpoint — the user must ask", async () => {
    const answerFn = vi.fn(async () => ({ answer: "x", based_on: 1 }));
    render(
      <KnowledgeView
        askFn={searchWithNote}
        answerFn={answerFn as unknown as typeof answerKnowledge}
      />,
    );
    ask("fed merger");
    await screen.findByRole("list", { name: "Your saved notes" });
    expect(answerFn).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Generate AI answer" })).toBeInTheDocument();
  });

  it("generates a labeled answer on click, grounded note phrasing included", async () => {
    const answerFn = vi.fn(async () => ({
      answer: "Per your saved note, the merger was approved.",
      based_on: 1,
    }));
    render(
      <KnowledgeView
        askFn={searchWithNote}
        answerFn={answerFn as unknown as typeof answerKnowledge}
      />,
    );
    ask("fed merger");
    await screen.findByRole("list", { name: "Your saved notes" });
    fireEvent.click(screen.getByRole("button", { name: "Generate AI answer" }));
    await waitFor(() => expect(answerFn).toHaveBeenCalledWith("fed merger"));
    expect(
      await screen.findByText("Per your saved note, the merger was approved."),
    ).toBeInTheDocument();
    // labeled as AI + the notes-only grounding note
    expect(screen.getByText("AI answer")).toBeInTheDocument();
    expect(screen.getByText(/only from your saved notes/)).toBeInTheDocument();
    // the button is consumed — one answer per turn
    expect(screen.queryByRole("button", { name: "Generate AI answer" })).toBeNull();
  });

  it("a failed generation shows a typed, retryable error — the hits stay", async () => {
    const answerFn = vi.fn(async () => {
      throw new Error("boom");
    });
    render(
      <KnowledgeView
        askFn={searchWithNote}
        answerFn={answerFn as unknown as typeof answerKnowledge}
      />,
    );
    ask("fed merger");
    await screen.findByRole("list", { name: "Your saved notes" });
    fireEvent.click(screen.getByRole("button", { name: "Generate AI answer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't generate the answer — try again.",
    );
    // retryable: the button is still there; the saved note never disappeared
    expect(screen.getByRole("button", { name: "Generate AI answer" })).toBeInTheDocument();
    expect(screen.getByText(/Fed approved the merger/)).toBeInTheDocument();
  });

  it("items-only hits offer no answer action — items never ground a synthesis", async () => {
    const askFn = vi.fn(async () => ({
      facts: [],
      saved: [],
      answer: null,
      items: [
        {
          id: "ti1",
          board_id: null,
          module_id: null,
          url: "https://www.sec.gov/news/x",
          title: "SEC market-structure rules",
          domain: "sec.gov",
          tier: "T1" as const,
          published: null,
          first_seen: "2026-07-07T00:00:00+00:00",
          status: "fetched" as const,
          failure_kind: null,
          degraded_reason: null,
          summary: null,
          similar_count: 0,
        },
      ],
    }));
    render(
      <KnowledgeView
        askFn={askFn as unknown as typeof searchKnowledge}
        answerFn={quietAnswerFn}
      />,
    );
    ask("market structure");
    await screen.findByRole("list", { name: "Tracked items" });
    expect(screen.queryByRole("button", { name: "Generate AI answer" })).toBeNull();
  });
});

describe("KnowledgeView tracked items in search (M15.2, M16.1 expression)", () => {
  const trackedItem = {
    id: "ti1",
    board_id: null,
    module_id: null,
    url: "https://www.sec.gov/news/x",
    title: "SEC market-structure rules",
    domain: "sec.gov",
    tier: "T1" as const,
    published: null,
    first_seen: "2026-07-07T00:00:00+00:00",
    status: "fetched" as const,
    failure_kind: null,
    degraded_reason: null,
    summary: "The SEC says its rulemaking enters a comment period.",
    similar_count: 2,
  };

  it("lists item hits labeled apart, with lite signals and zero check language", async () => {
    const askFn = vi.fn(async () => ({
      facts: [],
      saved: [],
      answer: null,
      items: [trackedItem],
    }));
    render(<KnowledgeView askFn={askFn as unknown as typeof searchKnowledge} />);
    ask("market structure");

    const items = await screen.findByRole("list", { name: "Tracked items" });
    // labeled as coming from the user's sources — never a verified fact
    expect(within(items).getByText("From your sources")).toBeInTheDocument();
    expect(within(items).getByRole("link", { name: "SEC market-structure rules" })).toHaveAttribute(
      "href",
      "/items/ti1",
    );
    // the legacy single-language summary is never rendered (M16.1) — a neutral
    // pending state shows until bilingual enrichment lands (M16.3)
    expect(within(items).queryByText(/rulemaking enters a comment period/)).toBeNull();
    expect(within(items).getByText("AI summary pending")).toBeInTheDocument();
    // the SAME lite signals as Today/Digest — code-first tier + dup/repost echo
    expect(within(items).getByText("T1 · primary/official")).toBeInTheDocument();
    expect(within(items).getByText("similar item from 2 other sources")).toBeInTheDocument();
    // the check surface is retired: no deep-check badge/button, no score
    expect(within(items).queryByText(/deep-checked/i)).toBeNull();
    expect(within(items).queryByRole("button")).toBeNull();
    expect(within(items).queryByText(/confidence · \d+\/100/)).toBeNull();
    // item-only hits: no AI answer block, and not the nothing-matched empty state
    expect(screen.queryByText("AI answer")).toBeNull();
    expect(screen.queryByText(/Nothing in your knowledge base matches/)).toBeNull();
  });
});

// --- M16.7: the distilled display layer ------------------------------------------


