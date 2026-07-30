import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeView } from "@/components/KnowledgeView";
import { LocaleProvider } from "@/lib/i18n";
import type { KnowledgeChat, KnowledgeChatSummary, KnowledgeNote } from "@/types/contract";

// Knowledge asks are persisted conversations: every ask is
// answered in one call and saved; the history list reopens or continues a chat.

const CHAT: KnowledgeChat = {
  id: "chat_1",
  title: "美联储最近做了什么?",
  messages: [
    { role: "user", content: "美联储最近做了什么?" },
    { role: "assistant", content: "来源提到美联储按兵不动;由此看,短期利率路径未变。" },
  ],
  created_at: "2026-07-24T08:00:00+00:00",
  updated_at: "2026-07-24T08:00:00+00:00",
  based_on: 12,
};

const SUMMARY: KnowledgeChatSummary = {
  id: "chat_1",
  title: "美联储最近做了什么?",
  updated_at: "2026-07-24T08:00:00+00:00",
  message_count: 2,
};

const NOTES: KnowledgeNote[] = [
  {
    id: "n1",
    board_id: "b1",
    kind: "user_note",
    title: "私募信贷的重定价还没走完",
    content: "利差在二季度全线走阔。",
    title_zh: "私募信贷的重定价还没走完",
    title_en: "Private-credit repricing is not done",
    content_zh: "利差在二季度全线走阔。",
    content_en: "Spreads widened through the second quarter.",
    citations: [],
    is_synthesized: false,
    regenerable: false,
    created_at: "2026-07-30T02:00:00+00:00",
  },
  {
    id: "n2",
    board_id: "b1",
    kind: "user_note",
    // an older note: no title, no localized copies — the fallbacks must carry it
    content: "SEC 规则进入公开评议期。",
    citations: [],
    is_synthesized: false,
    regenerable: false,
    created_at: "2026-07-29T02:00:00+00:00",
  },
];

function setup(overrides: Partial<Parameters<typeof KnowledgeView>[0]> = {}) {
  const listFn = vi.fn(async () => [] as KnowledgeChatSummary[]);
  const getFn = vi.fn(async () => CHAT);
  const createFn = vi.fn(async () => CHAT);
  const continueFn = vi.fn(async () => ({
    ...CHAT,
    messages: [
      ...CHAT.messages,
      { role: "user" as const, content: "对美股意味着什么?" },
      { role: "assistant" as const, content: "基于以上,波动可能有限(推断)。" },
    ],
  }));
  const deleteFn = vi.fn(async () => undefined);
  const notesFn = vi.fn(async () => NOTES);
  const renameFn = vi.fn(async (_b: string, _n: string, title: string) => ({
    ...NOTES[0],
    title,
    title_zh: title,
  }));
  render(
    <KnowledgeView
      listFn={listFn}
      getFn={getFn}
      createFn={createFn}
      continueFn={continueFn}
      deleteFn={deleteFn}
      notesFn={notesFn}
      renameFn={renameFn}
      {...overrides}
    />,
  );
  return { listFn, getFn, createFn, continueFn, deleteFn, notesFn, renameFn };
}

describe("KnowledgeView (persisted chats, 2026-07-24)", () => {
  it("asks → creates a chat and renders the labeled conversation", async () => {
    const { createFn } = setup();
    fireEvent.change(screen.getByLabelText("Ask daily"), {
      target: { value: "美联储最近做了什么?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(createFn).toHaveBeenCalledWith("美联储最近做了什么?", []));
    expect(await screen.findByText(/按兵不动/)).toBeInTheDocument();
    // AI labeling + grounding note survive
    expect(screen.getByText("AI answer")).toBeInTheDocument();
    expect(screen.getByText(/AI-generated over 12 knowledge-base entries/)).toBeInTheDocument();
  });

  it("a follow-up continues the SAME chat with its context", async () => {
    const { continueFn } = setup();
    fireEvent.change(screen.getByLabelText("Ask daily"), {
      target: { value: "美联储最近做了什么?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText(/按兵不动/);
    fireEvent.change(screen.getByLabelText("Ask daily"), {
      target: { value: "对美股意味着什么?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() =>
      expect(continueFn).toHaveBeenCalledWith("chat_1", "对美股意味着什么?", []),
    );
    expect(await screen.findByText(/波动可能有限/)).toBeInTheDocument();
  });

  it("history lists past chats; clicking one reopens it", async () => {
    const listFn = vi.fn(async () => [SUMMARY]);
    const { getFn } = setup({ listFn });
    expect(await screen.findByText("Chat history")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /美联储最近做了什么/ }));
    await waitFor(() => expect(getFn).toHaveBeenCalledWith("chat_1"));
    expect(await screen.findByText(/按兵不动/)).toBeInTheDocument();
  });

  it("deleting asks for confirmation, then removes the chat", async () => {
    const listFn = vi.fn(async () => [SUMMARY]);
    const { deleteFn } = setup({ listFn });
    await screen.findByText("Chat history");
    const del = screen.getByRole("button", { name: "Delete this chat" });
    fireEvent.click(del);
    expect(deleteFn).not.toHaveBeenCalled(); // first click only arms
    expect(del).toHaveTextContent("Delete?");
    fireEvent.click(del);
    await waitFor(() => expect(deleteFn).toHaveBeenCalledWith("chat_1"));
  });

  it("the open chat has its own delete button (confirm, then close + remove)", async () => {
    const { deleteFn } = setup();
    fireEvent.change(screen.getByLabelText("Ask daily"), {
      target: { value: "美联储最近做了什么?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText(/按兵不动/);
    const del = screen.getByRole("button", { name: "Delete chat" });
    fireEvent.click(del);
    expect(deleteFn).not.toHaveBeenCalled(); // first click only arms
    expect(del).toHaveTextContent("Delete?");
    fireEvent.click(del);
    await waitFor(() => expect(deleteFn).toHaveBeenCalledWith("chat_1"));
    // the conversation closed back to the intro
    await waitFor(() => expect(screen.queryByText(/按兵不动/)).not.toBeInTheDocument());
  });

  it("a failed ask shows a typed error and saves nothing", async () => {
    const createFn = vi.fn(async () => {
      throw new Error("boom");
    });
    setup({ createFn: createFn as never });
    fireEvent.change(screen.getByLabelText("Ask daily"), {
      target: { value: "问题" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't reach daily.");
  });
});

describe("the note pile on Knowledge", () => {
  it("lists the saved notes, and an untitled one falls back to its opening line", async () => {
    setup();
    expect(await screen.findByText("Private-credit repricing is not done")).toBeInTheDocument();
    // the older note has no title at all — its own first line stands in, so the
    // line shows twice: once as the title, once in the body
    expect(screen.getAllByText("SEC 规则进入公开评议期。")).toHaveLength(2);
  });

  it("bounds the ask to the notes the user picked, and back to all when cleared", async () => {
    const { createFn } = setup();
    const pick = await screen.findByLabelText(/Private-credit repricing is not done/);
    fireEvent.click(pick);
    expect(screen.getByText("Asking over 1 picked note(s)")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Ask daily"), { target: { value: "利差怎么样?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(createFn).toHaveBeenCalledWith("利差怎么样?", ["n1"]));

    fireEvent.click(screen.getByRole("button", { name: "Use all notes" }));
    expect(screen.getByText("Asking over every note")).toBeInTheDocument();
  });

  it("renames a note in the language the user is reading", async () => {
    const { renameFn } = setup();
    const card = (
      await screen.findByText("Private-credit repricing is not done")
    ).closest("article")!;
    fireEvent.mouseEnter(card);
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const field = screen.getByLabelText("Note title");
    fireEvent.change(field, { target: { value: "重定价还有第二段" } });
    fireEvent.keyDown(field, { key: "Enter" });
    await waitFor(() =>
      expect(renameFn).toHaveBeenCalledWith("b1", "n1", "重定价还有第二段", "en"),
    );
  });
});

describe("notes follow the language switch", () => {
  it("shows the Chinese copy under the zh locale", async () => {
    window.localStorage.clear();
    window.localStorage.setItem("daily.locale", "zh");
    render(
      <LocaleProvider>
        <KnowledgeView
          listFn={vi.fn(async () => [])}
          getFn={vi.fn(async () => CHAT)}
          createFn={vi.fn(async () => CHAT)}
          continueFn={vi.fn(async () => CHAT)}
          deleteFn={vi.fn(async () => undefined)}
          notesFn={vi.fn(async () => NOTES)}
          renameFn={vi.fn(async () => NOTES[0])}
        />
      </LocaleProvider>,
    );
    expect(await screen.findByText("私募信贷的重定价还没走完")).toBeInTheDocument();
    expect(screen.queryByText("Private-credit repricing is not done")).not.toBeInTheDocument();
  });
});
