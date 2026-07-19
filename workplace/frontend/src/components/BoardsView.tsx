"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import {
  ApiError,
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
import { trackedTitle } from "@/components/TrackedItems";
import { useIntlLocale, useLocale, useT } from "@/lib/i18n";
import type {
  Board,
  KnowledgeModule,
  KnowledgeNote,
  Subscription,
  TrackedItemCard,
} from "@/types/contract";

interface BoardsViewProps {
  // injectable so tests never hit the network
  boardsFn?: typeof queryBoards;
  notesFn?: typeof queryBoardNotes;
  createNoteFn?: typeof createNote;
  deleteBoardFn?: typeof deleteBoard;
  // M15.3: the board's module hierarchy + its sources and tracked items
  modulesFn?: typeof queryModules;
  createModuleFn?: typeof createModule;
  deleteModuleFn?: typeof deleteModule;
  assignModuleFn?: typeof assignSubscriptionModule;
  subscriptionsFn?: typeof querySubscriptions;
  digestFn?: typeof queryDigest;
}

function message(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** Knowledge boards (FR-15): single-operator topic collections. A board reads
 * as module chips → tracked items → the operator's own **notes**; management
 * chrome (module add/delete, source module moves) lives behind the Manage
 * toggle (owner 2026-07-18: "知识库太杂乱"). */
export function BoardsView({
  boardsFn = queryBoards,
  notesFn = queryBoardNotes,
  createNoteFn = createNote,
  deleteBoardFn = deleteBoard,
  modulesFn = queryModules,
  createModuleFn = createModule,
  deleteModuleFn = deleteModule,
  assignModuleFn = assignSubscriptionModule,
  subscriptionsFn = querySubscriptions,
  digestFn = queryDigest,
}: BoardsViewProps) {
  const [boards, setBoards] = useState<Board[] | null>(null);
  const [selected, setSelected] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  // M16.7 (knowledge map): per-board counts for the card list — computed in code
  // from existing endpoints; a counts failure degrades to name-only cards
  const [counts, setCounts] = useState<Record<string, BoardCounts>>({});
  const t = useT();

  useEffect(() => {
    if (!boards || boards.length === 0) return;
    let active = true;
    void (async () => {
      try {
        const [subs, digest, notesLists] = await Promise.all([
          subscriptionsFn(),
          digestFn({}),
          Promise.all(boards.map(async (b) => [b.id, await notesFn(b.id)] as const)),
        ]);
        if (!active) return;
        const tracked = digest.tracked ?? [];
        const notesByBoard = new Map(notesLists);
        const next: Record<string, BoardCounts> = {};
        for (const b of boards) {
          const items = tracked.filter((i) => i.board_id === b.id);
          const latest = items
            .map((i) => i.published ?? i.first_seen)
            .sort()
            .at(-1);
          next[b.id] = {
            sources: subs.filter((sub) => sub.board_id === b.id).length,
            items: items.length,
            notes: (notesByBoard.get(b.id) ?? []).length,
            latest: latest ?? null,
          };
        }
        setCounts(next);
      } catch {
        // keep name-only cards — the map must never block on its stats
      }
    })();
    return () => {
      active = false;
    };
  }, [boards, subscriptionsFn, digestFn, notesFn]);

  useEffect(() => {
    let active = true;
    boardsFn()
      .then((b) => {
        if (!active) return;
        setBoards(b);
        // open on content (M12.4): the first board's sections show without a click
        setSelected((prev) => prev ?? b[0] ?? null);
      })
      .catch((err) => active && setError(message(err, t("boards.errLoad"))));
    return () => {
      active = false;
    };
  }, [boardsFn]);

  return (
    <div className="space-y-6">
      {error && (
        <p role="alert" className="text-sm text-bad-fg">
          {error}
        </p>
      )}

      {boards && boards.length === 0 && (
        <p className="text-sm text-muted">{t("boards.none")}</p>
      )}
      {boards && boards.length > 0 && (
        <ul
          className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-2"
          role="list"
          aria-label={t("boards.list.aria")}
        >
          {boards.map((board) => (
            <li key={board.id}>
              <BoardCard
                board={board}
                counts={counts[board.id]}
                selected={selected?.id === board.id}
                onSelect={() => setSelected(board)}
              />
            </li>
          ))}
        </ul>
      )}

      {selected && (
        <BoardDetail
          key={selected.id}
          board={selected}
          notesFn={notesFn}
          createNoteFn={createNoteFn}
          modulesFn={modulesFn}
          createModuleFn={createModuleFn}
          deleteModuleFn={deleteModuleFn}
          assignModuleFn={assignModuleFn}
          subscriptionsFn={subscriptionsFn}
          digestFn={digestFn}
          onDelete={async () => {
            // M14.2 (owner beta feedback): boards are deletable from the UI. The
            // grouping + its notes go; sources and stored content stay.
            await deleteBoardFn(selected.id);
            setBoards((prev) => {
              const next = (prev ?? []).filter((b) => b.id !== selected.id);
              setSelected(next[0] ?? null);
              return next;
            });
          }}
        />
      )}
    </div>
  );
}

interface BoardCounts {
  sources: number;
  items: number; // within the digest's recent window (default 30d)
  notes: number;
  latest: string | null; // newest item's published/first_seen, if any
}

/** One board on the knowledge map (M16.7): the selectable card carries its own
 * counts (sources / recent items / notes / latest update) so the map reads at a
 * glance. Counts are presentation only — missing counts render a name-only card. */
function BoardCard({
  board,
  counts,
  selected,
  onSelect,
}: {
  board: Board;
  counts?: BoardCounts;
  selected: boolean;
  onSelect: () => void;
}) {
  const t = useT();
  const intlLocale = useIntlLocale();
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={board.name}
      onClick={onSelect}
      className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
        selected ? "border-accent bg-panel" : "border-line hover:border-muted"
      }`}
    >
      <span className="block text-sm font-medium text-ink">{board.name}</span>
      {counts && (
        <span className="mono tnum mt-1 block text-[11px] leading-relaxed text-faint">
          {t("boards.card.sources", { n: counts.sources })}
          {" · "}
          {t("boards.card.items", { n: counts.items })}
          {" · "}
          {t("boards.card.notes", { n: counts.notes })}
          {counts.latest &&
            ` · ${t("boards.card.latest", {
              date: new Date(counts.latest).toLocaleDateString(intlLocale),
            })}`}
        </span>
      )}
    </button>
  );
}

function BoardDetail({
  board,
  notesFn,
  createNoteFn,
  modulesFn,
  createModuleFn,
  deleteModuleFn,
  assignModuleFn,
  subscriptionsFn,
  digestFn,
  onDelete,
}: {
  board: Board;
  notesFn: typeof queryBoardNotes;
  createNoteFn: typeof createNote;
  modulesFn: typeof queryModules;
  createModuleFn: typeof createModule;
  deleteModuleFn: typeof deleteModule;
  assignModuleFn: typeof assignSubscriptionModule;
  subscriptionsFn: typeof querySubscriptions;
  digestFn: typeof queryDigest;
  onDelete: () => Promise<void>;
}) {
  const [notes, setNotes] = useState<KnowledgeNote[] | null>(null);
  const [modules, setModules] = useState<KnowledgeModule[] | null>(null);
  const [sources, setSources] = useState<Subscription[] | null>(null);
  const [items, setItems] = useState<TrackedItemCard[] | null>(null);
  // M15.3: the module filter narrows sources + items; notes stay board-level
  const [moduleFilter, setModuleFilter] = useState<string | null>(null);
  // owner 2026-07-18 ("知识库太杂乱"): the reading surface (chips → items →
  // notes) is the default;管理 chrome (module ×/add, source URLs + module
  // selects) only exists while this is on
  const [managing, setManaging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [noteText, setNoteText] = useState("");
  const [moduleName, setModuleName] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [confirmingModuleDelete, setConfirmingModuleDelete] = useState<string | null>(null);
  const t = useT();
  const { locale } = useLocale(); // M16.3: enrichment summaries follow the toggle

  useEffect(() => {
    let active = true;
    Promise.all([
      notesFn(board.id),
      modulesFn(board.id),
      subscriptionsFn(),
      digestFn({ boardId: board.id }),
    ])
      .then(([n, m, subs, digest]) => {
        if (!active) return;
        setNotes(n);
        setModules(m);
        setSources(subs.filter((s) => s.board_id === board.id));
        setItems(digest.tracked ?? []);
      })
      .catch((err) => active && setError(message(err, t("boards.errLoadBoard"))));
    return () => {
      active = false;
    };
  }, [board.id, notesFn, modulesFn, subscriptionsFn, digestFn]);

  async function addModule(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = moduleName.trim();
    if (!trimmed) return;
    setError(null);
    try {
      const module = await createModuleFn(board.id, trimmed);
      setModules((prev) => [...(prev ?? []), module]);
      setModuleName("");
    } catch (err) {
      setError(message(err, t("boards.modules.errCreate")));
    }
  }

  async function removeModule(moduleId: string) {
    setConfirmingModuleDelete(null);
    setError(null);
    try {
      await deleteModuleFn(moduleId);
      // only the grouping goes: member sources/items fall back to ungrouped
      setModules((prev) => (prev ?? []).filter((m) => m.id !== moduleId));
      setSources((prev) =>
        (prev ?? []).map((s) => (s.module_id === moduleId ? { ...s, module_id: null } : s)),
      );
      setItems((prev) =>
        (prev ?? []).map((i) => (i.module_id === moduleId ? { ...i, module_id: null } : i)),
      );
      setModuleFilter((prev) => (prev === moduleId ? null : prev));
    } catch (err) {
      setError(message(err, t("boards.modules.errDelete")));
    }
  }

  async function moveSource(sub: Subscription, moduleId: string | null) {
    setError(null);
    try {
      const updated = await assignModuleFn(sub.id, moduleId);
      setSources((prev) => (prev ?? []).map((s) => (s.id === sub.id ? updated : s)));
    } catch (err) {
      setError(message(err, t("boards.sources.errMove")));
    }
  }
  const userNotes = notes?.filter((n) => n.kind === "user_note") ?? [];

  async function addNote(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = noteText.trim();
    if (!trimmed) return;
    setError(null);
    try {
      const note = await createNoteFn(board.id, { kind: "user_note", content: trimmed });
      setNotes((prev) => [...(prev ?? []), note]);
      setNoteText("");
    } catch (err) {
      setError(message(err, t("boards.errNote")));
    }
  }


  if (notes === null && !error) {
    return <p className="text-sm text-muted">{t("boards.loading")}</p>;
  }

  return (
    <div className="space-y-6 border-t border-line pt-6">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold">{board.name}</h2>
        <button
          type="button"
          aria-pressed={managing}
          onClick={() => {
            setConfirmingModuleDelete(null);
            setManaging((prev) => !prev);
          }}
          className={`text-xs underline underline-offset-2 transition-colors ${
            managing ? "text-accent" : "text-faint hover:text-muted"
          }`}
        >
          {t("boards.manage")}
        </button>
        {!confirmingDelete ? (
          <button
            type="button"
            onClick={() => setConfirmingDelete(true)}
            className="text-xs text-faint underline underline-offset-2 transition-colors hover:text-bad-fg"
          >
            {t("boards.delete")}
          </button>
        ) : (
          // two-step inline confirm (M14.2): the copy says exactly what goes and
          // what stays — grouping + notes go, sources and stored content stay
          <span className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted">{t("boards.delete.confirmText")}</span>
            <button
              type="button"
              onClick={() => {
                setConfirmingDelete(false);
                void onDelete().catch(() => setError(t("boards.errDelete")));
              }}
              className="font-medium text-bad-fg underline underline-offset-2"
            >
              {t("boards.delete.confirmYes")}
            </button>
            <button
              type="button"
              onClick={() => setConfirmingDelete(false)}
              className="text-muted underline underline-offset-2"
            >
              {t("boards.delete.cancel")}
            </button>
          </span>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-bad-fg">
          {error}
        </p>
      )}

      {/* M15.3 — the knowledge hierarchy: board → module → source → item. The
          module filter narrows sources + items; notes below stay board-level.
          Reading first (owner 2026-07-18): chips filter, items read; the module
          ×/add form and the source-URL admin rows exist only in manage mode. */}
      <section aria-label={t("boards.modules.aria")} className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            aria-pressed={moduleFilter === null}
            onClick={() => setModuleFilter(null)}
            className={`rounded px-2 py-0.5 text-xs ${
              moduleFilter === null ? "bg-accent text-surface" : "border border-line text-muted"
            }`}
          >
            {t("boards.modules.all")}
          </button>
          {modules?.map((module) => (
            <span key={module.id} className="flex items-center gap-1">
              <button
                type="button"
                aria-pressed={moduleFilter === module.id}
                onClick={() => setModuleFilter(module.id)}
                className={`rounded px-2 py-0.5 text-xs ${
                  moduleFilter === module.id
                    ? "bg-accent text-surface"
                    : "border border-line text-muted"
                }`}
              >
                {module.name}
              </button>
              {managing &&
                (confirmingModuleDelete === module.id ? (
                  <span className="flex items-center gap-1 text-xs">
                    <span className="text-muted">{t("boards.modules.delete.confirmText")}</span>
                    <button
                      type="button"
                      onClick={() => void removeModule(module.id)}
                      className="font-medium text-bad-fg underline underline-offset-2"
                    >
                      {t("boards.modules.delete.confirmYes")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmingModuleDelete(null)}
                      className="text-muted underline underline-offset-2"
                    >
                      {t("boards.delete.cancel")}
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    aria-label={t("boards.modules.delete.aria", { name: module.name })}
                    onClick={() => setConfirmingModuleDelete(module.id)}
                    className="text-xs text-faint transition-colors hover:text-bad-fg"
                  >
                    ×
                  </button>
                ))}
            </span>
          ))}
          {managing && (
            <form onSubmit={addModule} className="flex items-center gap-1" noValidate>
              <input
                type="text"
                value={moduleName}
                onChange={(e) => setModuleName(e.target.value)}
                aria-label={t("boards.modules.add.aria")}
                placeholder={t("boards.modules.add.placeholder")}
                className="w-28 rounded border border-line px-2 py-0.5 text-xs"
              />
              <button type="submit" className="text-xs text-accent underline">
                {t("boards.modules.add")}
              </button>
            </form>
          )}
        </div>

        {/* sources in this board (manage mode only) — raw URLs + module moves
            are admin work, not reading */}
        {managing && (
          <div className="space-y-1.5 rounded-lg border border-line bg-panel p-3">
            <h4 className="text-xs font-medium text-muted">{t("boards.sources.heading")}</h4>
            {sources &&
              sources.filter((s) => moduleFilter === null || s.module_id === moduleFilter)
                .length === 0 && <p className="text-xs text-muted">{t("boards.sources.none")}</p>}
            <ul className="space-y-1.5" aria-label={t("boards.sources.aria")}>
              {sources
                ?.filter((s) => moduleFilter === null || s.module_id === moduleFilter)
                .map((sub) => (
                  <li key={sub.id} className="flex flex-wrap items-center justify-between gap-2">
                    <span className="mono min-w-0 break-all text-xs text-ink">{sub.input_url}</span>
                    <label className="flex items-center gap-1 text-xs text-faint">
                      {t("boards.sources.moveLabel")}
                      <select
                        value={sub.module_id ?? ""}
                        onChange={(e) => void moveSource(sub, e.target.value || null)}
                        className="rounded border border-line bg-surface px-1.5 py-0.5 text-xs text-muted"
                      >
                        <option value="">{t("boards.sources.unassigned")}</option>
                        {modules?.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  </li>
                ))}
            </ul>
          </div>
        )}

        {/* tracked items in this board — the reading list. Titles go to the
            item detail page (the original link lives there); summaries show the
            lede only. */}
        {items &&
          items.filter((i) => moduleFilter === null || i.module_id === moduleFilter).length ===
            0 && <p className="text-sm text-muted">{t("boards.items.none")}</p>}
        <ul className="space-y-4" aria-label={t("boards.items.aria")}>
          {items
            ?.filter((i) => moduleFilter === null || i.module_id === moduleFilter)
            .map((item) => (
              <li key={item.id} className="min-w-0 space-y-1">
                <p className="break-words text-[15px] font-medium leading-snug text-ink">
                  <Link
                    href={`/items/${item.id}`}
                    className="transition-colors hover:text-accent"
                  >
                    {trackedTitle(item, locale) ?? item.url ?? item.domain ?? "—"}
                  </Link>
                </p>
                {/* M16.3: the bilingual enrichment follows the locale; clamp to
                    the lede — the three-paragraph briefing lives on the detail */}
                {item.enrichment && (
                  <p className="line-clamp-2 max-w-[72ch] text-xs leading-relaxed text-muted">
                    <span className="badge mr-1.5 bg-panel text-faint">
                      {t("digest.ai.label")}
                    </span>
                    {locale === "zh" ? item.enrichment.summary_zh : item.enrichment.summary_en}
                  </p>
                )}
                {item.domain && <p className="mono text-xs text-faint">{item.domain}</p>}
              </li>
            ))}
        </ul>
      </section>

      {/* Operator notes — human-authored */}
      <section aria-label={t("boards.notes.aria")} className="space-y-2">
        <h3 className="text-sm font-semibold">{t("boards.notes.heading")}</h3>
        {userNotes.length === 0 && (
          <p className="text-sm text-muted">{t("boards.notes.none")}</p>
        )}
        <ul className="space-y-2">
          {userNotes.map((note) => (
            <li key={note.id} className="rounded border border-line p-3">
              <span className="rounded bg-panel px-2 py-0.5 text-xs text-muted">
                {t("boards.notes.note")}
              </span>
              <p className="mt-1 text-sm">{note.content}</p>
            </li>
          ))}
        </ul>
        <form onSubmit={addNote} className="flex gap-2" noValidate>
          <input
            type="text"
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            aria-label={t("boards.notes.add.aria")}
            placeholder={t("boards.notes.add.placeholder")}
            className="flex-1 rounded border border-line px-2 py-1 text-sm"
          />
          <button
            type="submit"
            className="btn-primary"
          >
            {t("boards.notes.add")}
          </button>
        </form>
      </section>
    </div>
  );
}
