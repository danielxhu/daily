import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { vi } from "vitest";

import { buildMockBoardNotes, buildMockBoards } from "@/mocks/fixtures";

// The page mounts BoardsView + KnowledgeView, both of which fetch on mount — mock
// the whole API surface so the page test never hits the network.
vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  queryBoards: async () => buildMockBoards(),
  createBoard: async () => ({}),
  deleteBoard: async () => undefined,
  queryBoardNotes: async (id: string) => buildMockBoardNotes(id),
  createNote: async () => ({}),
  distillBoard: async () => ({}),
  searchKnowledge: async () => ({ facts: [], saved: [] }),
  answerKnowledge: async () => ({ answer: null, based_on: 0 }),
  // M15.3: the board detail's hierarchy fetches
  queryModules: async () => [],
  createModule: async () => ({}),
  deleteModule: async () => undefined,
  assignSubscriptionModule: async () => ({}),
  querySubscriptions: async () => [],
  queryDigest: async () => ({ date: "2026-06-09", items: [], generated_at: "", tracked: [] }),
}));

import KnowledgePage from "@/app/knowledge/page";

describe("Knowledge page (M12.4: boards browse + ask on one page)", () => {
  it("shows the board-section browse and keeps the ask-daily conversation", async () => {
    render(<KnowledgePage />);
    expect(screen.getByRole("heading", { name: "Knowledge", level: 1 })).toBeInTheDocument();

    // boards browse is promoted into the page (from the old footer-level Boards page)
    const boards = screen.getByRole("region", { name: "Browse by board" });
    expect(boards).toBeInTheDocument();
    // the preset topic boards are offered, and the first one auto-opens its sections
    expect(await screen.findByRole("button", { name: "政治" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Notes" })).toBeInTheDocument();
    // the verified-facts region left the surface with the check retirement (M16.1)
    expect(screen.queryByRole("region", { name: "Verified facts" })).toBeNull();

    // "ask daily" is retained on the same page
    const ask = screen.getByRole("region", { name: "Ask daily" });
    expect(ask).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Ask daily" })).toBeInTheDocument();
    // M16.1: the whole live Knowledge page carries zero check-era language
    expect(document.body.textContent).not.toMatch(
      /verified fact|source of truth|credibility|verdict|stance|已核查事实|事实层|非信源/i,
    );
  });
});
