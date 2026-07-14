"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { TrackedItemLite, trackedTitle } from "@/components/TrackedItems";
import {
  ApiError,
  createNote,
  discussTrackedItem,
  getTrackedItem,
  refreshTrackedItem,
} from "@/lib/api";
import { useIntlLocale, useLocale, useT } from "@/lib/i18n";
import type { DiscussMessage, TrackedItemDetail } from "@/types/contract";

const TIER_KEY: Record<string, string> = {
  T1: "verify.tier.T1",
  "T1.5": "verify.tier.T1.5",
  T2: "verify.tier.T2",
};

interface ItemDetailViewProps {
  itemId: string;
  // injectable so tests never hit the network
  detailFn?: typeof getTrackedItem;
  refreshFn?: typeof refreshTrackedItem;
  createNoteFn?: typeof createNote;
  discussFn?: typeof discussTrackedItem;
}

/** The tracked-item detail page (M16.4): everything daily knows about ONE item,
 * in tracking language only — original link, the bilingual AI summary + why it
 * matters (labeled AI-generated), tags/entities, the stored source excerpt
 * ("Source says"), provenance, related items, and the user's note into the
 * board's Knowledge. No score, no verdict, no stance (v0.13). */
export function ItemDetailView({
  itemId,
  detailFn = getTrackedItem,
  refreshFn = refreshTrackedItem,
  createNoteFn = createNote,
  discussFn = discussTrackedItem,
}: ItemDetailViewProps) {
  const [detail, setDetail] = useState<TrackedItemDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshErr, setRefreshErr] = useState<string | null>(null);
  const autoStarted = useRef(false);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const t = useT();

  useEffect(
    () => () => {
      if (retryTimer.current) clearTimeout(retryTimer.current);
    },
    [],
  );

  useEffect(() => {
    let active = true;
    detailFn(itemId)
      .then((d) => active && setDetail(d))
      .catch((err) => {
        if (!active) return;
        setError(
          err instanceof ApiError && err.status === 404
            ? t("item.notFound")
            : err instanceof ApiError
              ? err.message
              : t("item.errLoad"),
        );
      });
    return () => {
      active = false;
    };
  }, [detailFn, itemId]);

  // owner 2026-07-10/13: fetching + summarizing must not need a click — opening
  // a pending item starts it automatically, and the AUTO attempt keeps retrying
  // quietly (busy tracker, backend restarting) instead of giving up after one
  // shot, which read as "automatic did nothing". The button stays as the manual
  // retry after a real, non-transient failure.
  useEffect(() => {
    if (
      detail !== null &&
      !autoStarted.current &&
      detail.item.url &&
      (!detail.item.enrichment || !detail.item.content_available)
    ) {
      autoStarted.current = true;
      void refresh({ auto: true, attempt: 1 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail]);

  const AUTO_RETRY_MS = 10_000;
  const AUTO_MAX_TRIES = 30; // ~5 minutes of quiet patience, then a visible error

  async function refresh(opts: { auto: boolean; attempt: number } = { auto: false, attempt: 1 }) {
    setRefreshing(true);
    setRefreshErr(null);
    try {
      setDetail(await refreshFn(itemId));
      setRefreshing(false);
    } catch (err) {
      const busy = err instanceof ApiError && err.status === 409;
      const transient = busy || !(err instanceof ApiError); // 409 or network/restart
      if (opts.auto && transient && opts.attempt < AUTO_MAX_TRIES) {
        // stay in the "fetching…" state and retry quietly
        retryTimer.current = setTimeout(
          () => void refresh({ auto: true, attempt: opts.attempt + 1 }),
          AUTO_RETRY_MS,
        );
        return;
      }
      setRefreshing(false);
      setRefreshErr(
        busy
          ? t("item.refresh.busy")
          : err instanceof ApiError
            ? err.message
            : t("item.errLoad"),
      );
    }
  }

  if (error) {
    return (
      <div className="space-y-4">
        <p role="alert" className="text-sm text-bad-fg">
          {error}
        </p>
        <Link href="/" className="text-sm text-accent hover:text-accent-strong">
          {t("item.back")}
        </Link>
      </div>
    );
  }
  if (detail === null) {
    return <p className="text-sm text-muted">{t("item.loading")}</p>;
  }
  return (
    <ItemDetail
      detail={detail}
      refreshing={refreshing}
      refreshErr={refreshErr}
      onRefresh={() => void refresh({ auto: false, attempt: 1 })}
      createNoteFn={createNoteFn}
      discussFn={discussFn}
    />
  );
}

function ItemDetail({
  detail,
  refreshing,
  refreshErr,
  onRefresh,
  createNoteFn,
  discussFn,
}: {
  detail: TrackedItemDetail;
  refreshing: boolean;
  refreshErr: string | null;
  onRefresh: () => void;
  createNoteFn: typeof createNote;
  discussFn: typeof discussTrackedItem;
}) {
  const t = useT();
  const { locale } = useLocale();
  const intlLocale = useIntlLocale();
  const item = detail.item;
  const e = item.enrichment;
  const summary = e ? (locale === "zh" ? e.summary_zh : e.summary_en) : null;
  const why = e ? (locale === "zh" ? e.why_zh : e.why_en) : null;
  const limits = e ? (locale === "zh" ? e.limitations_zh : e.limitations_en) : null;

  return (
    <article aria-label={t("item.aria")} className="space-y-8">
      <header className="space-y-2 border-b border-line pb-5">
        <Link href="/" className="text-xs text-faint transition-colors hover:text-muted">
          {t("item.back")}
        </Link>
        <h1 className="break-words text-[24px] font-semibold leading-snug tracking-[-0.01em] text-ink">
          {trackedTitle(item, locale) ?? t("today.tracked.untitled")}
        </h1>
        <div className="flex flex-wrap items-center gap-2 text-xs text-faint">
          {item.domain && <span className="mono">{item.domain}</span>}
          {item.tier && (
            <span className="badge bg-panel text-muted">{t(TIER_KEY[item.tier])}</span>
          )}
          <span className="tnum">
            {new Date(item.published ?? item.first_seen).toLocaleDateString(intlLocale)}
          </span>
          {item.url && (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="text-accent underline underline-offset-2 hover:text-accent-strong"
            >
              {t("tracked.original")}
            </a>
          )}
        </div>
      </header>

      {/* AI summary + why it matters — labeled, locale-following */}
      <section aria-label={t("item.summary.heading")} className="space-y-3">
        <div className="section-head">
          <h2 className="section-title">{t("item.summary.heading")}</h2>
          <span aria-hidden="true" className="section-rule" />
        </div>
        {summary ? (
          <>
            <p className="max-w-[65ch] text-sm leading-relaxed text-ink">{summary}</p>
            {why && (
              <p className="max-w-[65ch] text-sm leading-relaxed text-muted">
                <span className="badge mr-1.5 bg-panel text-faint">{t("item.why.heading")}</span>
                {why}
              </p>
            )}
            {(e?.tags ?? []).length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                {(e?.tags ?? []).map((tag) => (
                  <span key={tag} className="badge bg-panel text-muted">
                    {tag}
                  </span>
                ))}
              </div>
            )}
            {(e?.entities ?? []).length > 0 && (
              <p className="text-xs text-faint">
                {t("item.entities.heading")}: {(e?.entities ?? []).join(" · ")}
              </p>
            )}
            {limits && (
              <p className="text-xs italic text-faint">
                {t("item.limits.heading")}: {limits}
              </p>
            )}
            <p className="text-xs text-faint">{t("item.ai.note")}</p>
          </>
        ) : (
          <p className="max-w-[65ch] text-sm text-muted">{t("item.pending.note")}</p>
        )}
        {item.url && (!e || !item.content_available) && (
          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            className="btn-primary disabled:opacity-50"
          >
            {refreshing ? t("item.refreshing") : t("item.refresh")}
          </button>
        )}
        {refreshErr && (
          <p role="alert" className="text-xs text-bad-fg">
            {refreshErr}
          </p>
        )}
      </section>

      {/* owner 2026-07-10: the raw excerpt left the page — the (now fuller) AI
          briefing + the original link carry it; the stored text still grounds
          the discussion below */}
      <ItemDiscussPanel
        itemId={item.id}
        contentAvailable={item.content_available === true}
        discussFn={discussFn}
      />

      {/* provenance — tracking language only */}
      <section aria-label={t("item.provenance.heading")} className="space-y-3">
        <div className="section-head">
          <h2 className="section-title">{t("item.provenance.heading")}</h2>
          <span aria-hidden="true" className="section-rule" />
        </div>
        <dl className="grid max-w-[65ch] grid-cols-[auto,1fr] gap-x-6 gap-y-1.5 text-sm">
          {item.domain && (
            <>
              <dt className="text-faint">{t("item.provenance.domain")}</dt>
              <dd className="mono break-all text-muted">{item.domain}</dd>
            </>
          )}
          {item.tier && (
            <>
              <dt className="text-faint">{t("item.provenance.tier")}</dt>
              <dd className="text-muted">{t(TIER_KEY[item.tier])}</dd>
            </>
          )}
          {detail.fetch_method && (
            <>
              <dt className="text-faint">{t("item.provenance.method")}</dt>
              <dd className="mono text-muted">{detail.fetch_method}</dd>
            </>
          )}
          {item.published && (
            <>
              <dt className="text-faint">{t("item.provenance.published")}</dt>
              <dd className="tnum text-muted">
                {new Date(item.published).toLocaleString(intlLocale)}
              </dd>
            </>
          )}
          <dt className="text-faint">{t("item.provenance.firstSeen")}</dt>
          <dd className="tnum text-muted">
            {new Date(item.first_seen).toLocaleString(intlLocale)}
          </dd>
          <dt className="text-faint">{t("item.provenance.status")}</dt>
          <dd className="text-muted">{item.status}</dd>
        </dl>
      </section>

      {/* related — hints, never corroboration */}
      <section aria-label={t("item.related.heading")} className="space-y-3">
        <div className="section-head">
          <h2 className="section-title">{t("item.related.heading")}</h2>
          {(detail.related ?? []).length > 0 && (
            <span className="mono tnum text-[11px] text-faint">{(detail.related ?? []).length}</span>
          )}
          <span aria-hidden="true" className="section-rule" />
        </div>
        <p className="max-w-[65ch] text-xs text-faint">{t("item.related.note")}</p>
        {(detail.related ?? []).length === 0 ? (
          <p className="text-sm text-muted">{t("item.related.none")}</p>
        ) : (
          <ul className="row-list">
            {(detail.related ?? []).map((rel) => (
              <li key={rel.id}>
                <TrackedItemLite item={rel} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <ItemNote boardId={item.board_id} createNoteFn={createNoteFn} />
    </article>
  );
}

/** Discuss this item with the AI (M16.5) — the second half of the owner's
 * "点进任何一条信息都可以和 chat 讨论". Inline on the detail page (mobile-safe, no
 * overlay); the backend grounds replies ONLY in the item's stored excerpt + AI
 * summary and answers 证据不足 beyond them — the bounds note says so up front.
 * READ-ONLY: a discussion never writes anything. Without stored text there is
 * nothing to ground on, so the panel points at Fetch & summarize instead. */
function ItemDiscussPanel({
  itemId,
  contentAvailable,
  discussFn,
}: {
  itemId: string;
  contentAvailable: boolean;
  discussFn: typeof discussTrackedItem;
}) {
  const t = useT();
  const [messages, setMessages] = useState<DiscussMessage[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    // keep the newest turn in view as the thread grows
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, pending]);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    const question = input.trim();
    if (!question || pending) return;
    const next: DiscussMessage[] = [...messages, { role: "user", content: question }];
    setMessages(next);
    setInput("");
    setPending(true);
    setError(null);
    try {
      const res = await discussFn(itemId, next);
      setMessages([...next, { role: "assistant", content: res.reply }]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("item.discuss.err"));
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label={t("item.discuss.heading")} className="space-y-3">
      <div className="section-head">
        <h2 className="section-title">{t("item.discuss.heading")}</h2>
        <span aria-hidden="true" className="section-rule" />
      </div>
      {!contentAvailable ? (
        <p className="max-w-[65ch] text-sm text-muted">{t("item.discuss.needText")}</p>
      ) : (
        <div className="max-w-[70ch] space-y-3">
          <p className="text-xs leading-relaxed text-faint">{t("item.discuss.bounds")}</p>
          <ul
            ref={logRef}
            aria-label={t("item.discuss.log.aria")}
            className="max-h-80 space-y-3 overflow-y-auto"
          >
            {messages.length === 0 && !pending && (
              <li className="text-xs leading-relaxed text-faint">{t("item.discuss.empty")}</li>
            )}
            {messages.map((message, i) => (
              <li key={i} className={message.role === "user" ? "text-right" : ""}>
                {message.role === "user" ? (
                  <p className="inline-block max-w-[85%] break-words rounded-lg bg-panel px-3 py-2 text-left text-sm text-ink">
                    {message.content}
                  </p>
                ) : (
                  <p className="max-w-[65ch] break-words text-sm leading-relaxed text-muted">
                    <span className="badge mr-1.5 bg-panel text-faint">daily</span>
                    {message.content}
                  </p>
                )}
              </li>
            ))}
            {pending && <li className="text-xs text-faint">{t("item.discuss.thinking")}</li>}
          </ul>
          {error && (
            <p role="alert" className="text-xs text-bad-fg">
              {error}
            </p>
          )}
          <form onSubmit={send} className="flex items-center gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              aria-label={t("item.discuss.input.aria")}
              placeholder={t("item.discuss.placeholder")}
              className="input"
            />
            <button
              type="submit"
              disabled={pending || !input.trim()}
              className="btn-primary shrink-0"
            >
              {t("item.discuss.send")}
            </button>
          </form>
        </div>
      )}
    </section>
  );
}

/** The user's note on this item — a plain user_note into the item's board, so
 * it is searchable in Knowledge (M16.2 widened the search to user notes). */
function ItemNote({
  boardId,
  createNoteFn,
}: {
  boardId: string | null;
  createNoteFn: typeof createNote;
}) {
  const t = useT();
  const [text, setText] = useState("");
  const [state, setState] = useState<"idle" | "saved" | "error">("idle");

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const content = text.trim();
    if (!content || !boardId) return;
    try {
      await createNoteFn(boardId, { kind: "user_note", content });
      setState("saved");
      setText("");
    } catch {
      setState("error");
    }
  }

  return (
    <section aria-label={t("item.note.heading")} className="space-y-3">
      <div className="section-head">
        <h2 className="section-title">{t("item.note.heading")}</h2>
        <span aria-hidden="true" className="section-rule" />
      </div>
      {boardId === null ? (
        <p className="max-w-[65ch] text-sm text-muted">{t("item.note.noBoard")}</p>
      ) : (
        <form onSubmit={save} className="flex max-w-[70ch] flex-wrap items-end gap-2">
          <label className="block flex-1">
            <span className="sr-only">{t("item.note.heading")}</span>
            <input
              type="text"
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setState("idle");
              }}
              aria-label={t("item.note.heading")}
              placeholder={t("item.note.placeholder")}
              className="input"
            />
          </label>
          <button type="submit" className="btn-primary">
            {t("item.note.add")}
          </button>
          {state === "saved" && (
            <p role="status" className="w-full text-xs text-ok-fg">
              {t("item.note.saved")}
            </p>
          )}
          {state === "error" && (
            <p role="alert" className="w-full text-xs text-bad-fg">
              {t("item.note.err")}
            </p>
          )}
        </form>
      )}
    </section>
  );
}
