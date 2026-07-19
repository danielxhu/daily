"use client";

import { useState } from "react";
import Link from "next/link";

import { ApiError, answerKnowledge, searchKnowledge } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { TrackedItemLite } from "@/components/TrackedItems";
import type { KnowledgeNote, TrackedItemCard } from "@/types/contract";

type AnswerState =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "done"; text: string }
  | { state: "error"; message: string };

interface Turn {
  id: number;
  question: string;
  state: "loading" | "done" | "error";
  saved: KnowledgeNote[]; // the user's own saved notes (M13.2) — labeled apart
  items: TrackedItemCard[]; // M15.2: tracked items (keyword hits) — labeled
  answer: AnswerState; // M16.2: on-demand — NEVER filled by the search itself
  error?: string;
}

interface KnowledgeViewProps {
  // injectable so tests never hit the network
  askFn?: typeof searchKnowledge;
  answerFn?: typeof answerKnowledge;
}

/** Knowledge — "ask daily what it knows". Search is deterministic keyword
 * matching over what your sources published (tracked items) and what you saved
 * (notes) — it returns instantly and never calls an LLM (M16.2; the synchronous
 * synthesis was why search felt slow). The AI answer is an explicit per-turn
 * action: "Generate AI answer" synthesizes ONE reply grounded in the matching
 * saved notes and tracked-item summaries (2026-07-19). */
export function KnowledgeView({
  askFn = searchKnowledge,
  answerFn = answerKnowledge,
}: KnowledgeViewProps) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [nextId, setNextId] = useState(0);
  const t = useT();

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    const q = question.trim();
    if (!q) return;
    const id = nextId;
    setNextId(id + 1);
    setTurns((prev) => [
      ...prev,
      {
        id,
        question: q,
        state: "loading",
        saved: [],
        items: [],
        answer: { state: "idle" },
      },
    ]);
    setQuestion("");
    try {
      const result = await askFn(q);
      setTurns((prev) =>
        prev.map((t) =>
          t.id === id
            ? {
                ...t,
                state: "done",
                saved: result.saved,
                items: result.items ?? [],
              }
            : t,
        ),
      );
    } catch (err) {
      setTurns((prev) =>
        prev.map((turn) =>
          turn.id === id
            ? {
                ...turn,
                state: "error",
                error: err instanceof ApiError ? err.message : t("knowledge.errReach"),
              }
            : turn,
        ),
      );
    }
  }

  function setAnswer(id: number, answer: AnswerState) {
    setTurns((prev) => prev.map((turn) => (turn.id === id ? { ...turn, answer } : turn)));
  }

  async function generate(turn: Turn) {
    setAnswer(turn.id, { state: "loading" });
    try {
      const res = await answerFn(turn.question);
      if (res.answer) {
        setAnswer(turn.id, { state: "done", text: res.answer });
      } else {
        // the server saw no matching notes (list drifted since the search) —
        // surface it as a retryable message, never a silent nothing
        setAnswer(turn.id, { state: "error", message: t("knowledge.answer.err") });
      }
    } catch (err) {
      setAnswer(turn.id, {
        state: "error",
        message: err instanceof ApiError ? err.message : t("knowledge.answer.err"),
      });
    }
  }

  return (
    <div className="space-y-6">
      {turns.length === 0 ? (
        <p className="text-sm text-muted">
          {t("knowledge.intro")}
        </p>
      ) : (
        <ol className="space-y-6" aria-label={t("knowledge.turns.aria")}>
          {turns.map((turn) => (
            <li key={turn.id} className="space-y-2">
              <p className="text-sm font-medium text-ink">
                <span className="text-faint">{t("knowledge.you")}</span>
                {turn.question}
              </p>
              <Answer turn={turn} onGenerate={() => void generate(turn)} />
            </li>
          ))}
        </ol>
      )}

      <form onSubmit={ask} className="flex flex-wrap items-end gap-2">
        <label className="block flex-1">
          <span className="sr-only">{t("knowledge.input.aria")}</span>
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            aria-label={t("knowledge.input.aria")}
            placeholder={t("knowledge.input.placeholder")}
            className="input"
          />
        </label>
        <button type="submit" className="btn-primary">
          {t("knowledge.ask")}
        </button>
      </form>
    </div>
  );
}

function Answer({ turn, onGenerate }: { turn: Turn; onGenerate: () => void }) {
  const t = useT();
  if (turn.state === "loading") {
    return <p className="text-sm text-muted">{t("knowledge.loading")}</p>;
  }
  if (turn.state === "error") {
    return (
      <p role="alert" className="text-sm text-bad-fg">
        {turn.error}
      </p>
    );
  }
  if (turn.saved.length === 0 && turn.items.length === 0) {
    return (
      <p className="text-sm text-muted">
        <span className="text-faint">{t("knowledge.daily")}</span>
        {t("knowledge.noFacts").split("{sourcesLink}")[0]}
        <Link href="/tracking" className="text-accent hover:text-accent-strong">
          {t("knowledge.sourcesLinkText")}
        </Link>
        {t("knowledge.noFacts").split("{sourcesLink}")[1]}
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {/* M16.2: the AI answer is on demand — grounded in the saved notes AND
          tracked-item summaries (2026-07-19), so any hit offers it */}
      {(turn.saved.length > 0 || turn.items.length > 0) && (
        <OnDemandAnswer answer={turn.answer} onGenerate={onGenerate} />
      )}
      {/* M15.2: tracked items (keyword hits) — the SAME lite expression as
          Today/Digest: tier, date, echo hint, typed status (M15.4) */}
      {turn.items.length > 0 && (
        <ul className="space-y-2" aria-label={t("knowledge.items.aria")}>
          {turn.items.map((item) => (
            <li key={item.id} className="space-y-1.5 rounded-lg border border-line bg-panel p-3">
              <span className="badge bg-panel text-faint">{t("knowledge.items.badge")}</span>
              <TrackedItemLite item={item} />
            </li>
          ))}
        </ul>
      )}
      {/* the user's own saved notes (M13.2): labeled apart, badge per kind */}
      {turn.saved.length > 0 && (
        <ul className="space-y-2" aria-label={t("knowledge.saved.aria")}>
          {turn.saved.map((note) => (
            <li key={note.id} className="rounded-lg border border-line bg-panel p-3">
              <span className="badge bg-warn-bg text-warn-fg">
                {note.kind === "user_note"
                  ? t("knowledge.note.badge")
                  : t("knowledge.saved.badge")}
              </span>
              <p className="mt-1.5 break-words text-sm text-ink">{note.content}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function OnDemandAnswer({
  answer,
  onGenerate,
}: {
  answer: AnswerState;
  onGenerate: () => void;
}) {
  const t = useT();
  if (answer.state === "loading") {
    return (
      <p role="status" className="text-xs text-muted">
        {t("knowledge.answer.generating")}
      </p>
    );
  }
  if (answer.state === "done") {
    return (
      <div className="rounded-lg border border-line bg-panel p-3">
        <span className="badge bg-accent/15 text-accent-strong">
          {t("knowledge.answer.label")}
        </span>
        <p className="mt-1.5 max-w-[65ch] break-words text-sm leading-relaxed text-ink">
          {answer.text}
        </p>
        <p className="mt-1.5 text-xs text-faint">{t("knowledge.answer.note")}</p>
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={onGenerate}
        className="text-xs text-accent underline underline-offset-2 transition-colors hover:text-accent-strong"
      >
        {t("knowledge.answer.generate")}
      </button>
      {answer.state === "error" && (
        <p role="alert" className="text-xs text-bad-fg">
          {answer.message}
        </p>
      )}
    </div>
  );
}
