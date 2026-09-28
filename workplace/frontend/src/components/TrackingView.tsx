"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";

import {
  ApiError,
  createSubscription,
  deleteSubscription,
  pollNow,
  createBoard,
  deleteBoard,
  queryBoards,
  queryDigest,
  renameSubscription,
  querySubscriptions,
} from "@/lib/api";
import type { PollReport, PollSubReport } from "@/lib/api";
import { trackedTitle } from "@/components/TrackedItems";
import { boardName } from "@/lib/boards";
import { useIntlLocale, useLocale, useT } from "@/lib/i18n";
import type {
  Board,
  Subscription,
  SubscriptionFailureKind,
  TrackedItemCard,
} from "@/types/contract";

// The add form asks only what the URL can't answer: treat a plain page as a feed
// (the type is auto-detected) or watch it for new links. `autodiscover`/`platform`
// stay valid backend values for existing sources.
const MODES: Subscription["mode"][] = ["direct", "homepage_diff"];

// Isomorphic with backend app/tracking/health.py SUBSCRIPTION_NEXT_ACTION (§6.6):
// a failed source shows the user a NEXT STEP, not just a log line.
const FAILURE_KEY: Record<SubscriptionFailureKind, string> = {
  gone: "tracking.failure.gone",
  rate_limited: "tracking.failure.rate_limited",
  parse_or_render_unfit: "tracking.failure.parse_or_render_unfit",
  network: "tracking.failure.network",
  system_anomaly: "tracking.failure.system_anomaly",
  items_unfetchable: "tracking.failure.items_unfetchable",
};

const MODE_KEY: Record<Subscription["mode"], string> = {
  direct: "tracking.mode.direct",
  autodiscover: "tracking.mode.autodiscover",
  platform: "tracking.mode.platform",
  homepage_diff: "tracking.mode.homepage_diff",
};

// What a source is, read from its URL — mirrors poll.py's routing predicates
// (`_is_single_video` / `_is_single_content` / …). Display only: the backend decides
// handling, so a mislabel here is cosmetic.
function sourceKindKey(sub: Pick<Subscription, "input_url" | "mode">): string {
  if (sub.mode === "homepage_diff") return "kind.homepage";
  let host = "";
  let path = "";
  try {
    const u = new URL(sub.input_url);
    host = u.hostname.replace(/^www\./, "").replace(/^m\./, "");
    path = u.pathname;
  } catch {
    return "kind.feed";
  }
  const bvid = /[?&]bvid=BV[0-9A-Za-z]+/.test(sub.input_url);
  if (["youtu.be", "b23.tv", "v.douyin.com"].includes(host)) return "kind.video";
  if (host === "xhslink.com") return "kind.note";
  if (host.endsWith("youtube.com") && (path === "/watch" || path.startsWith("/shorts/")))
    return "kind.video";
  if (host === "bilibili.com" && (path.startsWith("/video/") || bvid)) return "kind.video";
  if (host === "douyin.com" && path.startsWith("/video/")) return "kind.video";
  if (host === "xiaohongshu.com" && (path.startsWith("/explore/") || path.startsWith("/discovery/item/")))
    return "kind.note";
  if (host.endsWith("reddit.com") && path.includes("/comments/")) return "kind.post";
  if (host === "space.bilibili.com") return "kind.channel";
  if (host === "douyin.com" && path.startsWith("/user/")) return "kind.channel";
  if (host.endsWith("youtube.com") && /^\/(@|channel\/|c\/|user\/)/.test(path)) return "kind.channel";
  if (host === "weibo.com" || host === "weibo.cn") return "kind.social";
  return "kind.feed";
}

/** One source's own items, inline on its row. Newest first. */
function SourceContent({ items }: { items: TrackedItemCard[] }) {
  const t = useT();
  const { locale } = useLocale();
  const intlLocale = useIntlLocale();
  if (items.length === 0) {
    return <p className="mt-2 text-xs text-faint">{t("tracking.content.none")}</p>;
  }
  const sorted = [...items].sort((a, b) =>
    (b.published ?? b.first_seen).localeCompare(a.published ?? a.first_seen),
  );
  return (
    <ul className="mt-2 divide-y divide-line border-t border-line">
      {sorted.map((item) => (
        <li key={item.id} className="flex items-baseline gap-3 py-2">
          <span className="mono tnum w-20 shrink-0 text-[11px] text-faint">
            {item.published
              ? new Date(item.published).toLocaleDateString(intlLocale)
              : t("tracking.content.undated")}
          </span>
          <span className="min-w-0 text-[13px] leading-snug text-ink">
            <Link href={`/items/${item.id}`} className="transition-colors hover:text-accent">
              {trackedTitle(item, locale) ?? item.url ?? "—"}
            </Link>
          </span>
        </li>
      ))}
    </ul>
  );
}

interface TrackingViewProps {
  // injectable so tests never hit the network
  subscriptionsFn?: typeof querySubscriptions;
  createFn?: typeof createSubscription;
  deleteFn?: typeof deleteSubscription;
  pollFn?: typeof pollNow;
  boardsFn?: typeof queryBoards;
  createBoardFn?: typeof createBoard;
  deleteBoardFn?: typeof deleteBoard;
  renameFn?: typeof renameSubscription;
  digestFn?: typeof queryDigest;
}

function message(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function checkSummary(
  report: PollReport,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  // M16.1: the check retirement — the poll summary counts sources and items,
  // never verification outcomes (written facts / corroboration are dormant).
  const failed = report.subscriptions.filter((s) => !s.ok).length;
  const parts = [
    report.polled === 1
      ? t("tracking.summary.checked", { count: report.polled })
      : t("tracking.summary.checked_plural", { count: report.polled }),
  ];
  // M13.1: items that failed ingestion are counted honestly, never silently dropped
  const itemsFailed = report.subscriptions.reduce((n, s) => n + (s.items_failed ?? 0), 0);
  if (itemsFailed > 0) {
    parts.push(
      itemsFailed === 1
        ? t("tracking.summary.itemsFailed", { count: itemsFailed })
        : t("tracking.summary.itemsFailed_plural", { count: itemsFailed }),
    );
  }
  if (failed > 0) {
    parts.push(
      failed === 1
        ? t("tracking.summary.failed", { count: failed })
        : t("tracking.summary.failed_plural", { count: failed }),
    );
  }
  // M13.4: a first check picks up only the latest few — say so, never silently
  const backlog = report.subscriptions.reduce((n, s) => n + (s.backlog_skipped ?? 0), 0);
  if (backlog > 0) parts.push(t("tracking.summary.backlog", { count: backlog }));
  // M14.5: a first check defers slow audio/video transcription — delayed, not lost
  const deferred = report.subscriptions.reduce((n, s) => n + (s.items_deferred ?? 0), 0);
  if (deferred > 0) parts.push(t("tracking.summary.deferred", { count: deferred }));
  if (report.system_anomaly) parts.push(t("tracking.summary.anomaly"));
  return `${parts.join(" · ")}.`;
}

/** Sources this check flagged: a typed reason + the one-click recovery path.
 * Rendered from the poll report itself so the failure is visible the moment the
 * check finishes (M13.1) — the row-level health catches up via the refresh. */
function CheckFailures({ report }: { report: PollReport }) {
  const t = useT();
  const flagged = report.subscriptions.filter((s) => !s.ok || (s.items_failed ?? 0) > 0);
  if (flagged.length === 0) return null;
  return (
    <ul className="row-list text-xs" aria-label={t("tracking.itemFailures.aria")}>
      {flagged.map((s: PollSubReport) => (
        <li key={s.subscription_id} className="space-y-1">
          <p className="break-words font-medium text-ink">{s.input_url}</p>
          {s.failure_kind && (
            <p className="text-warn-fg">{t(FAILURE_KEY[s.failure_kind])}</p>
          )}
          {(s.items_failed ?? 0) > 0 && (
            <p className="text-faint">
              {t("tracking.items.failedLine", {
                failed: s.items_failed ?? 0,
                total: (s.items_ok ?? 0) + (s.items_failed ?? 0),
              })}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Sources management (FR-3 / §6.4). The operator adds/removes the sources daily
 * watches (feed / homepage / channel URLs) and sees each one's mode, board, and
 * health (last error + next step). NFR-6 honesty banner up top: checking is not
 * real-time, runs only while the machine is on, and homepage-watching is heuristic.
 * daily watches the sources the operator chose — never topic discovery. */
export function TrackingView({
  subscriptionsFn = querySubscriptions,
  createFn = createSubscription,
  deleteFn = deleteSubscription,
  pollFn = pollNow,
  boardsFn = queryBoards,
  createBoardFn = createBoard,
  deleteBoardFn = deleteBoard,
  renameFn = renameSubscription,
  digestFn = queryDigest,
}: TrackingViewProps) {
  const [subs, setSubs] = useState<Subscription[] | null>(null);
  const [items, setItems] = useState<TrackedItemCard[]>([]);
  const [openSource, setOpenSource] = useState<string | null>(null);
  const [boards, setBoards] = useState<Board[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [name, setName] = useState(""); // optional display name (2026-07-19)
  const [mode, setMode] = useState<Subscription["mode"]>("direct");
  const [boardId, setBoardId] = useState("");
  // inline rename: which source row is being renamed, and the draft text
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  // boards are CREATED here, where sources are added — not in
  // Knowledge (deleting the last board left no way to make one at add time)
  const [newBoardName, setNewBoardName] = useState("");
  const [boardErr, setBoardErr] = useState<string | null>(null);
  // boards are DELETED here too — two-step confirm per group
  const [confirmingBoardDelete, setConfirmingBoardDelete] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState<string | null>(null);
  const [checkReport, setCheckReport] = useState<PollReport | null>(null);
  const t = useT();
  const localizedBoards = boards.map((b) => ({ ...b, name: boardName(b, t) }));

  useEffect(() => {
    let active = true;
    subscriptionsFn()
      .then((s) => active && setSubs(s))
      .catch((err) => active && setError(message(err, t("tracking.errLoad"))));
    // boards are grouping garnish — a failure must never block the sources list
    boardsFn()
      .then((b) => active && setBoards(b))
      .catch(() => active && setBoards([]));
    // 365 is the endpoint's maximum window; a failure just drops the affordance
    digestFn({ windowDays: 365 })
      .then((d) => active && setItems(d.tracked ?? []))
      .catch(() => active && setItems([]));
    return () => {
      active = false;
    };
  }, [subscriptionsFn, boardsFn, digestFn]);

  async function addBoard() {
    const name = newBoardName.trim();
    if (!name) return;
    try {
      const board = await createBoardFn(name);
      setBoards((prev) => [...prev, board]);
      setBoardId(board.id); // the new board is what the user is about to use
      setNewBoardName("");
    } catch (err) {
      setBoardErr(err instanceof ApiError ? err.message : t("tracking.newBoard.err"));
    }
  }

  async function handleAdd(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) {
      setError(t("tracking.errEmpty"));
      return;
    }
    setError(null);
    try {
      const created = await createFn({
        input_url: trimmed,
        mode,
        board_id: boardId.trim() || null,
        name: name.trim() || null,
      });
      setSubs((prev) => [created, ...(prev ?? [])]);
      setUrl("");
      setName("");
      setBoardId("");
    } catch (err) {
      setError(message(err, t("tracking.errAdd")));
    }
  }

  async function handleBoardDelete(id: string) {
    setConfirmingBoardDelete(null);
    setError(null);
    try {
      await deleteBoardFn(id);
      // the backend cascades: the board's sources (and their items) go with it
      setBoards((prev) => prev.filter((b) => b.id !== id));
      setSubs((prev) => (prev ?? []).filter((s) => s.board_id !== id));
      setBoardId((prev) => (prev === id ? "" : prev));
    } catch (err) {
      setError(message(err, t("boards.errDelete")));
    }
  }

  async function handleRename(id: string) {
    setError(null);
    try {
      const updated = await renameFn(id, renameDraft.trim() || null);
      setSubs((prev) => (prev ?? []).map((s) => (s.id === id ? updated : s)));
      setRenamingId(null);
      setRenameDraft("");
    } catch (err) {
      setError(message(err, t("tracking.rename.err")));
    }
  }

  async function handleRemove(id: string) {
    setError(null);
    try {
      await deleteFn(id);
      setSubs((prev) => (prev ?? []).filter((s) => s.id !== id));
    } catch (err) {
      setError(message(err, t("tracking.errRemove")));
    }
  }

  async function handleCheck() {
    setError(null);
    setCheckResult(null);
    setCheckReport(null);
    setChecking(true);
    try {
      const report = await pollFn();
      setCheckResult(checkSummary(report, t));
      setCheckReport(report);
      // refresh so each source's updated health / last error shows after the check
      setSubs(await subscriptionsFn());
    } catch (err) {
      // M14.4: a concurrent check is refused with 409 — that's information, not an
      // error: say it's running instead of painting the banner red
      if (err instanceof ApiError && err.status === 409) {
        setCheckResult(t("tracking.checking.already"));
      } else {
        setError(message(err, t("tracking.errCheck")));
      }
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleCheck}
          disabled={checking}
          className="btn-primary shrink-0"
        >
          {checking ? t("tracking.checking") : t("tracking.checkBtn")}
        </button>
        {checkResult && (
          <p role="status" className="text-xs text-muted">
            {checkResult}
          </p>
        )}
      </div>
      {checkReport && <CheckFailures report={checkReport} />}

      <form onSubmit={handleAdd} className="space-y-3 rounded-xl border border-line bg-card p-4 shadow-card" noValidate>
        <label className="block text-sm font-medium text-ink">
          {t("tracking.sourceUrl.label")}
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            aria-label={t("tracking.sourceUrl.label")}
            placeholder={t("tracking.sourceUrl.placeholder")}
            className="input mt-1"
          />
        </label>
        {/* an optional display name (URLs alone are hard to tell apart) */}
        <label className="block text-sm font-medium text-ink">
          {t("tracking.name.label")}
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label={t("tracking.name.label")}
            placeholder={t("tracking.name.placeholder")}
            className="input mt-1"
          />
        </label>
        <div className="flex flex-wrap gap-3">
          <label className="block text-sm font-medium text-ink">
            {t("tracking.mode.label")}
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as Subscription["mode"])}
              aria-label={t("tracking.mode.label")}
              className="mt-1 block rounded-lg border border-line bg-card px-3 py-2 text-sm text-ink"
            >
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {t(MODE_KEY[m])}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm font-medium text-ink">
            {t("tracking.boardId.label")}
            <select
              value={boardId}
              onChange={(e) => setBoardId(e.target.value)}
              aria-label={t("tracking.boardId.label")}
              className="mt-1 block rounded-lg border border-line bg-panel px-3 py-2 text-sm text-ink"
            >
              <option value="">{t("tracking.board.none")}</option>
              {boards.map((board) => (
                <option key={board.id} value={board.id}>
                  {boardName(board, t)}
                </option>
              ))}
            </select>
            <span className="mt-2 flex items-center gap-1.5">
              <input
                type="text"
                value={newBoardName}
                onChange={(e) => {
                  setNewBoardName(e.target.value);
                  setBoardErr(null);
                }}
                aria-label={t("tracking.newBoard.aria")}
                placeholder={t("tracking.newBoard.placeholder")}
                className="block w-40 rounded-lg border border-line bg-panel px-2 py-1 text-xs text-ink"
              />
              <button
                type="button"
                onClick={() => void addBoard()}
                className="btn-ghost px-2 py-1 text-xs"
              >
                {t("tracking.newBoard.add")}
              </button>
            </span>
            {boardErr && (
              <span role="alert" className="mt-1 block text-xs font-normal text-bad-fg">
                {boardErr}
              </span>
            )}
          </label>
        </div>
        <p className="max-w-[60ch] text-xs text-faint">{t("tracking.mode.help")}</p>
        <button type="submit" className="btn-primary">
          {t("tracking.addSource")}
        </button>
      </form>

      {error && (
        <p role="alert" className="text-sm text-bad-fg">
          {error}
        </p>
      )}

      {!error && subs === null && <p className="text-sm text-muted">{t("tracking.loading")}</p>}
      {subs && subs.length === 0 && boards.length === 0 && (
        <p className="text-sm text-muted">{t("tracking.none")}</p>
      )}
      {subs && (subs.length > 0 || boards.length > 0) && (
        <ul className="row-list" aria-label={t("tracking.list.aria")}>
          {groupByBoard(subs, localizedBoards, t("tracking.group.none")).map((group) => (
            <Fragment key={group.id ?? "none"}>
              {/* board group header — presentation row, not a source item. Every
                  board renders (even empty) so it can be deleted here;
                  deletion is a two-step confirm, cascade stated. */}
              <li role="presentation" className="!py-1.5" style={{ background: "rgb(var(--panel) / 0.4)" }}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span>
                    <span className="text-[11px] font-semibold text-faint">{group.name}</span>
                    <span className="mono tnum ml-2 text-[11px] text-faint">{group.items.length}</span>
                  </span>
                  {group.id !== null &&
                    boards.some((b) => b.id === group.id) &&
                    (confirmingBoardDelete === group.id ? (
                      <span className="flex flex-wrap items-center gap-2 text-[11px]">
                        <span className="text-muted">{t("boards.delete.confirmText")}</span>
                        <button
                          type="button"
                          onClick={() => void handleBoardDelete(group.id as string)}
                          className="font-medium text-bad-fg underline underline-offset-2"
                        >
                          {t("boards.delete.confirmYes")}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmingBoardDelete(null)}
                          className="text-muted underline underline-offset-2"
                        >
                          {t("boards.delete.cancel")}
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmingBoardDelete(group.id as string)}
                        aria-label={t("tracking.board.remove.aria", { name: group.name })}
                        className="text-[11px] text-faint underline underline-offset-2 transition-colors hover:text-bad-fg"
                      >
                        {t("boards.delete")}
                      </button>
                    ))}
                </div>
              </li>
              {group.items.map((sub) => (
            <li key={sub.id} className="space-y-1">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  {/* the user-given name leads, the URL stays visible below it
                      (URLs alone are hard to tell apart); both open the source */}
                  <p className="truncate text-sm font-medium text-ink">
                    <a
                      href={sub.input_url}
                      target="_blank"
                      rel="noreferrer"
                      title={t("tracking.open.aria", { url: sub.input_url })}
                      className="transition-colors hover:text-accent hover:underline underline-offset-2"
                    >
                      {sub.name || sub.input_url}
                    </a>
                  </p>
                  {sub.name && (
                    <a
                      href={sub.input_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mono block truncate text-xs text-faint transition-colors hover:text-accent"
                    >
                      {sub.input_url}
                    </a>
                  )}
                  <p className="text-xs text-faint">{t(sourceKindKey(sub))}</p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span
                    className={`badge ${
                      sub.health === "unhealthy" ? "bg-bad-bg text-bad-fg" : "bg-ok-bg text-ok-fg"
                    }`}
                  >
                    {t(
                      sub.health === "unhealthy"
                        ? "tracking.health.unhealthy"
                        : "tracking.health.ok",
                    )}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setRenamingId(sub.id);
                      setRenameDraft(sub.name ?? "");
                    }}
                    aria-label={t("tracking.rename.aria", { url: sub.input_url })}
                    className="text-xs text-muted underline underline-offset-2 hover:text-ink"
                  >
                    {t("tracking.rename")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setOpenSource((prev) => (prev === sub.id ? null : sub.id))}
                    aria-expanded={openSource === sub.id}
                    aria-label={t("tracking.content.aria", { url: sub.input_url })}
                    className="text-xs text-muted underline underline-offset-2 hover:text-ink"
                  >
                    {t("tracking.content", {
                      count: items.filter((i) => i.subscription_id === sub.id).length,
                    })}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleRemove(sub.id)}
                    aria-label={t("tracking.remove.aria", { url: sub.input_url })}
                    className="text-xs text-muted underline underline-offset-2 hover:text-ink"
                  >
                    {t("tracking.remove")}
                  </button>
                </div>
              </div>
              {openSource === sub.id && (
                <SourceContent items={items.filter((i) => i.subscription_id === sub.id)} />
              )}
              {renamingId === sub.id && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void handleRename(sub.id);
                  }}
                  className="flex items-center gap-2"
                  noValidate
                >
                  <input
                    type="text"
                    value={renameDraft}
                    onChange={(e) => setRenameDraft(e.target.value)}
                    aria-label={t("tracking.rename.input.aria")}
                    placeholder={t("tracking.name.placeholder")}
                    className="block w-56 rounded-lg border border-line bg-panel px-2 py-1 text-xs text-ink"
                    autoFocus
                  />
                  <button type="submit" className="text-xs text-accent underline underline-offset-2">
                    {t("tracking.rename.save")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setRenamingId(null)}
                    className="text-xs text-muted underline underline-offset-2"
                  >
                    {t("tracking.rename.cancel")}
                  </button>
                </form>
              )}
              {(sub.subscription_failure_kind || sub.last_error) && (
                <div className="text-xs">
                  {sub.subscription_failure_kind && (
                    <p className="text-warn-fg">{t(FAILURE_KEY[sub.subscription_failure_kind])}</p>
                  )}
                  {sub.last_error && (
                    <p className="text-faint">{t("tracking.lastError", { error: sub.last_error })}</p>
                  )}
                </div>
              )}
            </li>
              ))}
            </Fragment>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Group subscriptions by topic board for display: known boards first (in board
 * order, INCLUDING empty ones — an empty board must still render so it can be
 * deleted), then boards the list no longer knows (deleted —
 * shown by raw id), then the ungrouped bucket. Pure presentation. */
function groupByBoard(
  subs: Subscription[],
  boards: Board[],
  noneLabel: string,
): { id: string | null; name: string; items: Subscription[] }[] {
  const byBoard = new Map<string | null, Subscription[]>();
  for (const sub of subs) {
    const key = sub.board_id ?? null;
    const bucket = byBoard.get(key);
    if (bucket) bucket.push(sub);
    else byBoard.set(key, [sub]);
  }
  const groups: { id: string | null; name: string; items: Subscription[] }[] = [];
  for (const board of boards) {
    groups.push({ id: board.id, name: board.name, items: byBoard.get(board.id) ?? [] });
  }
  for (const [key, items] of byBoard) {
    if (key !== null && !boards.some((b) => b.id === key)) {
      groups.push({ id: key, name: key, items });
    }
  }
  const ungrouped = byBoard.get(null);
  if (ungrouped) groups.push({ id: null, name: noneLabel, items: ungrouped });
  return groups;
}
