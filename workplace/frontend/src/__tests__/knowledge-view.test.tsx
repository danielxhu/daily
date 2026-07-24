import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeView } from "@/components/KnowledgeView";
import type { KnowledgeChat, KnowledgeChatSummary } from "@/types/contract";

// Knowledge asks are persisted conversations (owner 2026-07-24): every ask is
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
  render(
    <KnowledgeView
      listFn={listFn}
      getFn={getFn}
      createFn={createFn}
      continueFn={continueFn}
      deleteFn={deleteFn}
      {...overrides}
    />,
  );
  return { listFn, getFn, createFn, continueFn, deleteFn };
}

describe("KnowledgeView (persisted chats, 2026-07-24)", () => {
  it("asks → creates a chat and renders the labeled conversation", async () => {
    const { createFn } = setup();
    fireEvent.change(screen.getByLabelText("Ask daily"), {
      target: { value: "美联储最近做了什么?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(createFn).toHaveBeenCalledWith("美联储最近做了什么?"));
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
      expect(continueFn).toHaveBeenCalledWith("chat_1", "对美股意味着什么?"),
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
