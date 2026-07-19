import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BoardsView } from "@/components/BoardsView";
import {
  assignSubscriptionModule,
  createModule,
  createNote,
  deleteBoard,
  deleteModule,
  queryBoardNotes,
  queryBoards,
  queryDigest,
  queryModules,
  querySubscriptions,
} from "@/lib/api";
import {
  buildMockBoardNotes,
  buildMockBoards,
  buildMockDigest,
  buildMockModules,
  buildMockSubscriptions,
} from "@/mocks/fixtures";
import type { KnowledgeNote } from "@/types/contract";

function setup(
  overrides: {
    notesFn?: typeof queryBoardNotes;
    createNoteFn?: typeof createNote;
    modulesFn?: typeof queryModules;
  } = {},
) {
  const boardsFn = vi.fn(async () => buildMockBoards());
  const notesFn = vi.fn(overrides.notesFn ?? (async (boardId: string) => buildMockBoardNotes(boardId)));
  const createNoteFn = vi.fn(
    overrides.createNoteFn ??
      (async (boardId: string, note: { kind: string; content: string; citations?: string[] }) =>
        ({
          id: "n_new",
          board_id: boardId,
          kind: note.kind,
          content: note.content,
          citations: note.citations ?? [],
          is_synthesized: false,
          regenerable: false,
          created_at: "2026-06-10T00:00:00+00:00",
        }) as KnowledgeNote),
  );
  const deleteBoardFn = vi.fn(async () => undefined);
  // M15.3 hierarchy fetches: modules + board sources + board-scoped tracked items
  const modulesFn = vi.fn(overrides.modulesFn ?? (async (boardId: string) => buildMockModules(boardId)));
  const createModuleFn = vi.fn(
    async (boardId: string, name: string) => ({
      id: `m_${name.toLowerCase()}`,
      board_id: boardId,
      name,
      created_at: "2026-06-10T00:00:00+00:00",
    }),
  );
  const deleteModuleFn = vi.fn(async () => undefined);
  const assignModuleFn = vi.fn(async (subId: string, moduleId: string | null) => ({
    ...buildMockSubscriptions()[0],
    id: subId,
    module_id: moduleId,
  }));
  const subscriptionsFn = vi.fn(async () => buildMockSubscriptions());
  const digestFn = vi.fn(async (opts: { boardId?: string } = {}) => buildMockDigest(opts.boardId));
  render(
    <BoardsView
      boardsFn={boardsFn as unknown as typeof queryBoards}
      notesFn={notesFn as unknown as typeof queryBoardNotes}
      createNoteFn={createNoteFn as unknown as typeof createNote}
      deleteBoardFn={deleteBoardFn as unknown as typeof deleteBoard}
      modulesFn={modulesFn as unknown as typeof queryModules}
      createModuleFn={createModuleFn as unknown as typeof createModule}
      deleteModuleFn={deleteModuleFn as unknown as typeof deleteModule}
      assignModuleFn={assignModuleFn as unknown as typeof assignSubscriptionModule}
      subscriptionsFn={subscriptionsFn as unknown as typeof querySubscriptions}
      digestFn={digestFn as unknown as typeof queryDigest}
    />,
  );
  return {
    boardsFn, notesFn, createNoteFn, deleteBoardFn,
    modulesFn, createModuleFn, deleteModuleFn, assignModuleFn, subscriptionsFn, digestFn,
  };
}

const openFinance = async () => {
  await waitFor(() => expect(screen.getByRole("button", { name: "Finance" })).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Finance" }));
  // wait for the detail to finish loading (the regions replace "Loading board…")
  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Notes" })).toBeInTheDocument(),
  );
};

// management chrome (module ×/add, source rows) lives behind this toggle
const openManage = () => fireEvent.click(screen.getByRole("button", { name: "Manage" }));

describe("BoardsView", () => {
  it("adds a free-text user note", async () => {
    const { createNoteFn } = setup();
    await openFinance();
    const notes = screen.getByRole("region", { name: "Notes" });
    fireEvent.change(within(notes).getByLabelText("New note"), {
      target: { value: "Q3 guidance call on the 14th" },
    });
    fireEvent.click(within(notes).getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(createNoteFn).toHaveBeenCalledWith("b_finance", {
        kind: "user_note",
        content: "Q3 guidance call on the 14th",
      }),
    );
    expect(await screen.findByText("Q3 guidance call on the 14th")).toBeInTheDocument();
  });

  it("deletes a board after a two-step confirm that says what goes and stays (M14.2)", async () => {
    const { deleteBoardFn } = setup();
    await openFinance();
    // step 1: the quiet delete affordance in the detail header
    fireEvent.click(screen.getByRole("button", { name: "Delete board" }));
    // the confirm copy covers ALL real consequences (M14.2 review): the board,
    // its TRACKED SOURCES (backend deletes board-scoped subscriptions), and its
    // notes go — nothing else
    expect(
      screen.getByText(
        /removes this board, the tracked sources assigned to it .with their discovered items., and its notes.*Nothing else is affected/,
      ),
    ).toBeInTheDocument();
    // step 2: confirm → DELETE fires, the chip disappears, selection moves on
    fireEvent.click(screen.getByRole("button", { name: "Delete it" }));
    await waitFor(() => expect(deleteBoardFn).toHaveBeenCalledWith("b_finance"));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Finance" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "政治" })).toBeInTheDocument(); // others stay
  });

  it("cancelling the delete confirm keeps the board (M14.2)", async () => {
    const { deleteBoardFn } = setup();
    await openFinance();
    fireEvent.click(screen.getByRole("button", { name: "Delete board" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(deleteBoardFn).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Finance" })).toBeInTheDocument();
    // back to the quiet affordance
    expect(screen.getByRole("button", { name: "Delete board" })).toBeInTheDocument();
  });

});

describe("BoardsView knowledge hierarchy (M15.3)", () => {
  it("reads clean by default; Manage reveals sources + module admin (2026-07-18)", async () => {
    setup();
    await openFinance();
    // modules of this board render as filter chips
    const section = screen.getByRole("region", { name: "Modules and sources" });
    expect(within(section).getByRole("button", { name: "Rates" })).toBeInTheDocument();
    // tracked items are the reading list (check badges retired by M16.1)
    const items = within(section).getByRole("list", { name: "Tracked items in this board" });
    expect(
      within(items).getByRole("link", { name: "Board-scoped tracked item" }),
    ).toBeInTheDocument();
    // …and titles go to the item detail page, not straight off-site
    expect(
      within(items).getByRole("link", { name: "Board-scoped tracked item" }),
    ).toHaveAttribute("href", expect.stringMatching(/^\/items\//));
    // M16.3: the bilingual enrichment renders in the active locale (en default);
    // the legacy single-language line never renders (M16.1)
    expect(
      within(items).getByText(/The source says a board-scoped update landed./),
    ).toBeInTheDocument();
    expect(within(items).queryByText(/LEGACY-ONLY/)).toBeNull();
    expect(within(section).queryByText(/deeply checked/i)).toBeNull();
    // the reading surface carries NO management chrome…
    expect(within(section).queryByRole("list", { name: "Sources in this board" })).toBeNull();
    expect(within(section).queryByLabelText("New module name")).toBeNull();
    expect(within(section).queryByRole("button", { name: "Delete module Rates" })).toBeNull();
    // …until Manage is on: source rows (with module selector) + module admin
    openManage();
    const sources = within(section).getByRole("list", { name: "Sources in this board" });
    expect(within(sources).getByText(/federalreserve.gov/)).toBeInTheDocument();
    expect(within(section).getByLabelText("New module name")).toBeInTheDocument();
  });

  it("creates a module in the board", async () => {
    const { createModuleFn } = setup();
    await openFinance();
    openManage();
    const section = screen.getByRole("region", { name: "Modules and sources" });
    fireEvent.change(within(section).getByLabelText("New module name"), {
      target: { value: "AI chips" },
    });
    fireEvent.click(within(section).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(createModuleFn).toHaveBeenCalledWith("b_finance", "AI chips"));
    expect(await within(section).findByRole("button", { name: "AI chips" })).toBeInTheDocument();
  });

  it("removes a module after an honest un-group confirm — content survives", async () => {
    const { deleteModuleFn } = setup();
    await openFinance();
    openManage();
    const section = screen.getByRole("region", { name: "Modules and sources" });
    fireEvent.click(within(section).getByRole("button", { name: "Delete module Rates" }));
    // the confirm says exactly what happens: grouping only, content stays
    expect(
      within(section).getByText("Only the grouping goes — sources and content stay."),
    ).toBeInTheDocument();
    fireEvent.click(within(section).getByRole("button", { name: "Remove it" }));
    await waitFor(() => expect(deleteModuleFn).toHaveBeenCalledWith("m_rates"));
    expect(within(section).queryByRole("button", { name: "Rates" })).not.toBeInTheDocument();
    // sources and items are still listed (now ungrouped)
    expect(within(section).getByText(/federalreserve.gov/)).toBeInTheDocument();
    expect(
      within(section).getByRole("link", { name: "Board-scoped tracked item" }),
    ).toBeInTheDocument();
  });

  it("moves a source into a module via the selector", async () => {
    const { assignModuleFn } = setup();
    await openFinance();
    openManage();
    const section = screen.getByRole("region", { name: "Modules and sources" });
    const sources = within(section).getByRole("list", { name: "Sources in this board" });
    fireEvent.change(within(sources).getByLabelText(/Module:/), {
      target: { value: "m_rates" },
    });
    await waitFor(() => expect(assignModuleFn).toHaveBeenCalledWith("sub_fed", "m_rates"));
  });

  it("the module filter narrows sources and items; All restores", async () => {
    setup();
    await openFinance();
    openManage();
    const section = screen.getByRole("region", { name: "Modules and sources" });
    fireEvent.click(within(section).getByRole("button", { name: "Rates" }));
    // nothing is assigned to Rates yet → both lists show their honest empty states
    expect(
      within(section).getByText(/No sources assigned to this board yet/),
    ).toBeInTheDocument();
    expect(within(section).queryByRole("link", { name: "Board-scoped tracked item" })).toBeNull();
    expect(within(section).getByText(/No tracked items here yet/)).toBeInTheDocument();
    fireEvent.click(within(section).getByRole("button", { name: "All" }));
    expect(
      await within(section).findByRole("link", { name: "Board-scoped tracked item" }),
    ).toBeInTheDocument();
  });
});
