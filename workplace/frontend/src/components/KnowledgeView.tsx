"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import {
  ApiError,
  continueKnowledgeChat,
  createKnowledgeChat,
  deleteKnowledgeChat,
  getKnowledgeChat,
  listKnowledgeChats,
} from "@/lib/api";
import { useIntlLocale, useT } from "@/lib/i18n";
import type { KnowledgeChat, KnowledgeChatSummary } from "@/types/contract";

interface KnowledgeViewProps {
  // injectable so tests never hit the network
  listFn?: typeof listKnowledgeChats;
  getFn?: typeof getKnowledgeChat;
  createFn?: typeof createKnowledgeChat;
  continueFn?: typeof continueKnowledgeChat;
  deleteFn?: typeof deleteKnowledgeChat;
}

/** Knowledge — "ask daily what it knows", as persisted conversations (owner
 * 2026-07-24). Every ask is answered over the whole knowledge base in one call
 * and saved into the current chat; the history list reopens an old chat to
 * re-read it or keep asking with its context. Deleting a chat never touches
 * the notes/items it talked about. */
export function KnowledgeView({
  listFn = listKnowledgeChats,
  getFn = getKnowledgeChat,
  createFn = createKnowledgeChat,
  continueFn = continueKnowledgeChat,
  deleteFn = deleteKnowledgeChat,
}: KnowledgeViewProps) {
  const [question, setQuestion] = useState("");
  const [chats, setChats] = useState<KnowledgeChatSummary[]>([]);
  const [active, setActive] = useState<KnowledgeChat | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const t = useT();
  const intlLocale = useIntlLocale();

  useEffect(() => {
    let alive = true;
    listFn()
      .then((c) => alive && setChats(c))
      .catch(() => alive && setChats([]));
    return () => {
      alive = false;
    };
  }, [listFn]);

  async function refreshList() {
    try {
      setChats(await listFn());
    } catch {
      // the list is garnish — the active conversation already rendered
    }
  }

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    const q = question.trim();
    if (!q || sending) return;
    setSending(true);
    setError(null);
    try {
      const chat = active ? await continueFn(active.id, q) : await createFn(q);
      setActive(chat);
      setQuestion("");
      await refreshList();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("knowledge.errReach"));
    } finally {
      setSending(false);
    }
  }

  async function open(id: string) {
    setError(null);
    try {
      setActive(await getFn(id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("knowledge.errReach"));
    }
  }

  async function remove(id: string) {
    if (confirmDelete !== id) {
      setConfirmDelete(id);
      return;
    }
    setConfirmDelete(null);
    try {
      await deleteFn(id);
      if (active?.id === id) setActive(null);
      await refreshList();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("knowledge.errReach"));
    }
  }

  return (
    <div className="space-y-6">
      {/* the active conversation (or the intro) */}
      {active ? (
        <div className="space-y-1">
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-sm font-medium text-ink">{active.title}</p>
            <button
              type="button"
              onClick={() => {
                setActive(null);
                setError(null);
              }}
              className="btn-ghost shrink-0 text-xs"
            >
              {t("knowledge.chat.new")}
            </button>
          </div>
          <ol className="space-y-3" aria-label={t("knowledge.turns.aria")}>
            {active.messages.map((m, i) => (
              <li key={i} className="text-sm">
                {m.role === "user" ? (
                  <p className="font-medium text-ink">
                    <span className="text-faint">{t("knowledge.you")}</span>
                    {m.content}
                  </p>
                ) : (
                  <div className="rounded-lg border border-line bg-panel p-3">
                    <span className="badge bg-accent/15 text-accent-strong">
                      {t("knowledge.answer.label")}
                    </span>
                    <p className="mt-1.5 max-w-[65ch] whitespace-pre-line break-words text-sm leading-relaxed text-ink">
                      {m.content}
                    </p>
                  </div>
                )}
              </li>
            ))}
          </ol>
          <p className="pt-1 text-xs text-faint">
            {active.based_on != null
              ? t("knowledge.chat.basedOn", { count: active.based_on })
              : t("knowledge.answer.note")}
          </p>
        </div>
      ) : (
        <p className="text-sm text-muted">{t("knowledge.intro")}</p>
      )}

      <form onSubmit={ask} className="flex flex-wrap items-end gap-2">
        <label className="block flex-1">
          <span className="sr-only">{t("knowledge.input.aria")}</span>
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            aria-label={t("knowledge.input.aria")}
            placeholder={t(active ? "knowledge.chat.followUp" : "knowledge.input.placeholder")}
            className="input"
          />
        </label>
        <button type="submit" disabled={sending} className="btn-primary disabled:opacity-50">
          {sending ? t("knowledge.chat.sending") : t("knowledge.ask")}
        </button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-bad-fg">
          {error}
          {error.includes("empty") && (
            <>
              {" "}
              <Link href="/tracking" className="text-accent hover:text-accent-strong">
                {t("knowledge.sourcesLinkText")}
              </Link>
            </>
          )}
        </p>
      )}

      {/* chat history (owner 2026-07-24): reopen to re-read or continue */}
      {chats.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-faint">
            {t("knowledge.chat.history")}
          </h3>
          <ul aria-label={t("knowledge.chat.history.aria")} className="space-y-1">
            {chats.map((chat) => (
              <li key={chat.id} className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void open(chat.id)}
                  className={`min-w-0 flex-1 truncate rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
                    active?.id === chat.id
                      ? "bg-panel text-ink"
                      : "text-muted hover:bg-panel/60 hover:text-ink"
                  }`}
                >
                  {chat.title}
                  <span className="mono tnum ml-2 text-xs text-faint">
                    {new Date(chat.updated_at).toLocaleDateString(intlLocale)} ·{" "}
                    {Math.floor(chat.message_count / 2)}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => void remove(chat.id)}
                  aria-label={t("knowledge.chat.delete.aria")}
                  className={`shrink-0 rounded px-1.5 py-1 text-xs transition-colors ${
                    confirmDelete === chat.id
                      ? "bg-bad-bg text-bad-fg"
                      : "text-faint hover:text-bad-fg"
                  }`}
                >
                  {confirmDelete === chat.id ? t("knowledge.chat.delete.confirm") : "×"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
