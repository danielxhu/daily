"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { queryBoards, queryModules } from "@/lib/api";
import { useIntlLocale, useLocale, useT } from "@/lib/i18n";
import type { Board, KnowledgeModule, TrackedItemCard } from "@/types/contract";

const TIER_KEY: Record<NonNullable<TrackedItemCard["tier"]>, string> = {
  T1: "verify.tier.T1",
  "T1.5": "verify.tier.T1.5",
  T2: "verify.tier.T2",
};

/** The item title in the ACTIVE locale (the language toggle
 * must carry the title too). The enrichment carries a faithful translation of
 * the source's own title; items without one (older cache / no enrichment)
 * degrade to the original title. */
export function trackedTitle(
  item: TrackedItemCard,
  locale: string,
): string | null {
  const e = item.enrichment;
  const translated = locale === "zh" ? e?.title_zh : e?.title_en;
  return translated ?? item.title ?? null;
}

/** One tracked item's honest status line — only shown when something is off.
 * A clean fetched item needs no caveat; the section note already says summaries
 * only restate the source. */
function trackedStatus(item: TrackedItemCard, t: (k: string) => string): string | null {
  if (item.status === "failed" && item.failure_kind) {
    return t(`verify.failure.${item.failure_kind}`);
  }
  // deferred = queued for the background transcriber (2026-07-20): no stale
  // "click to fetch" instruction — the worker handles it, the row stays quiet
  if (item.status === "deferred") return null;
  if (item.status === "new") return t("today.tracked.processing");
  if (item.degraded_reason) return t("today.tracked.degraded");
  return null;
}

/** One tracked item's lite expression (M15.4, trimmed by M16.1): title +
 * provenance link, AI briefing, then the meta line — domain, code-first tier,
 * date, the dup/repost echo hint, and the typed status. The check surface left
 * the product with M16.1.
 * Shared by Today, the full Digest, and Knowledge search hits
 * so the semantics never drift between surfaces. */
export function TrackedItemLite({ item }: { item: TrackedItemCard }) {
  const t = useT();
  const intlLocale = useIntlLocale();
  const { locale } = useLocale();

  const status = trackedStatus(item, t);
  const when = item.published ?? item.first_seen;
  const similar = item.similar_count ?? 0;
  // M16.3: the bilingual enrichment carries BOTH languages — the toggle switches
  // instantly, no call, no cache miss. The deprecated
  // single-language `summary` is never consumed (M16.1).
  const summary = item.enrichment
    ? locale === "zh"
      ? item.enrichment.summary_zh
      : item.enrichment.summary_en
    : null;
  return (
    <div className="min-w-0 space-y-1">
      {/* M16.4: the title opens the item's OWN detail page;
          the original link moves to the meta line below */}
      <p className="serif break-words text-[16px] font-semibold leading-snug text-ink">
        <Link href={`/items/${item.id}`} className="transition-colors hover:text-accent">
          {trackedTitle(item, locale) ?? item.url ?? t("today.tracked.untitled")}
        </Link>
      </p>
      {summary ? (
        <p className="max-w-[65ch] text-xs leading-relaxed text-muted">
          <span className="badge mr-1.5 bg-panel text-faint">{t("digest.ai.label")}</span>
          {summary}
        </p>
      ) : (
        // no enrichment yet (legacy item / failed generation): an honest pending
        // state for fetched items — failed/deferred rows let the status speak
        item.status === "fetched" && (
          <p className="text-xs italic text-faint">{t("tracked.summary.pending")}</p>
        )
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-faint">
        {item.domain && <span className="mono">{item.domain}</span>}
        {item.tier && (
          <span className="badge bg-panel text-muted">{t(TIER_KEY[item.tier])}</span>
        )}
        <span className="tnum">{new Date(when).toLocaleDateString(intlLocale)}</span>
        {/* M15.4 dup/repost hint — a triage nudge, not corroboration */}
        {similar > 0 && (
          <span>
            {similar === 1
              ? t("tracked.similar", { count: similar })
              : t("tracked.similar_plural", { count: similar })}
          </span>
        )}
        {status && <span className="italic">{status}</span>}
        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="text-accent underline underline-offset-2 transition-colors hover:text-accent-strong"
          >
            {t("tracked.original")}
          </a>
        )}
      </div>
    </div>
  );
}

// --- board/module grouping (M16.6, AIHOT-informed read surface) ---------------

/** The names the grouped briefing renders with — boards + each board's modules.
 * Purely presentational; grouping NEVER filters or re-orders items. */
export interface TrackedGrouping {
  boards: Board[];
  modulesByBoard: Record<string, KnowledgeModule[]>;
}

/** Load the grouping names for a set of tracked items (M16.6). Boards come in
 * one call; modules are fetched only for boards that actually have module-tagged
 * items. Any failure degrades to an EMPTY grouping — items always render (flat);
 * a naming fetch must never hide content. */
export function useTrackedGrouping(
  items: TrackedItemCard[],
  boardsFn: typeof queryBoards = queryBoards,
  modulesFn: typeof queryModules = queryModules,
): TrackedGrouping | null {
  const [grouping, setGrouping] = useState<TrackedGrouping | null>(null);
  useEffect(() => {
    if (items.length === 0) return;
    let active = true;
    void (async () => {
      try {
        const boards = await boardsFn();
        const withModules = new Set(
          items.filter((i) => i.module_id && i.board_id).map((i) => i.board_id),
        );
        const entries = await Promise.all(
          boards
            .filter((b) => withModules.has(b.id))
            .map(async (b) => [b.id, await modulesFn(b.id)] as const),
        );
        if (active) setGrouping({ boards, modulesByBoard: Object.fromEntries(entries) });
      } catch {
        if (active) setGrouping({ boards: [], modulesByBoard: {} });
      }
    })();
    return () => {
      active = false;
    };
  }, [items, boardsFn, modulesFn]);
  return grouping;
}

interface ModuleGroup {
  key: string;
  name: string | null; // null → the board's un-moduled items (no sub-head)
  items: TrackedItemCard[];
}

interface ItemGroup {
  key: string;
  name: string | null; // null → items whose source has no (known) board
  items: TrackedItemCard[]; // every item in the group, for the stats line
  modules: ModuleGroup[];
}

/** Group items by board, then by module — boards in API order, no-board last;
 * WITHIN a group the incoming (reverse-chronological) order is preserved
 * untouched. Heat or any other signal is never a sort key (FR-14). */
function groupTracked(items: TrackedItemCard[], grouping: TrackedGrouping): ItemGroup[] {
  const known = new Set(grouping.boards.map((b) => b.id));
  const byBoard = new Map<string | null, TrackedItemCard[]>();
  for (const item of items) {
    const key = item.board_id && known.has(item.board_id) ? item.board_id : null;
    const list = byBoard.get(key) ?? [];
    list.push(item);
    byBoard.set(key, list);
  }
  const build = (key: string, name: string | null, list: TrackedItemCard[]): ItemGroup => {
    const moduleNames = new Map(
      (name && grouping.modulesByBoard[key] ? grouping.modulesByBoard[key] : []).map((m) => [
        m.id,
        m.name,
      ]),
    );
    const modules: ModuleGroup[] = [];
    for (const item of list) {
      // unknown module ids fold into the un-moduled bucket — never a fake name
      const moduleName = item.module_id ? (moduleNames.get(item.module_id) ?? null) : null;
      const moduleKey = moduleName ? `${key}:${item.module_id}` : `${key}:_`;
      const existing = modules.find((m) => m.key === moduleKey);
      if (existing) existing.items.push(item);
      else modules.push({ key: moduleKey, name: moduleName, items: [item] });
    }
    return { key, name, items: list, modules };
  };
  const groups: ItemGroup[] = [];
  for (const board of grouping.boards) {
    const list = byBoard.get(board.id);
    if (list) groups.push(build(board.id, board.name, list));
  }
  const rest = byBoard.get(null);
  if (rest) groups.push(build("_none", null, rest));
  return groups;
}

/** One group's compact stats line (M16.6, Digest): item count, distinct source
 * count, latest update, tier distribution. Computed in code from the cards —
 * zero LLM, zero extra requests (NFR-7). */
function GroupStats({ items }: { items: TrackedItemCard[] }) {
  const t = useT();
  const intlLocale = useIntlLocale();
  const sources = new Set(items.map((i) => i.domain).filter(Boolean)).size;
  const latest = items
    .map((i) => i.published ?? i.first_seen)
    .sort()
    .at(-1);
  const tiers = (["T1", "T1.5", "T2"] as const)
    .map((tier) => ({ tier, n: items.filter((i) => i.tier === tier).length }))
    .filter(({ n }) => n > 0);
  return (
    <span className="mono tnum text-[11px] text-faint">
      {t("tracked.stats.counts", { items: items.length, sources })}
      {latest &&
        ` · ${t("tracked.stats.latest", { date: new Date(latest).toLocaleDateString(intlLocale) })}`}
      {tiers.length > 0 && ` · ${tiers.map(({ tier, n }) => `${tier} ×${n}`).join(" · ")}`}
    </span>
  );
}

/** Tracked items as first-class knowledge (M15.1a, v0.12 P0): visible the
 * moment a poll discovers them, whatever later enrichment does. `controls`
 * (M16.1) lets the host surface put its own affordances — the Today window
 * selector, the full-digest link — into the section head; `empty` is the
 * host's empty state (rendered instead of the list). `grouping` (M16.6) turns
 * the flat list into board/module groups; `stats` adds the per-group stats
 * line (the Digest read surface). */
export function TrackedItemsSection({
  items,
  controls,
  empty,
  grouping,
  stats = false,
}: {
  items: TrackedItemCard[];
  controls?: React.ReactNode;
  empty?: React.ReactNode;
  grouping?: TrackedGrouping | null;
  stats?: boolean;
}) {
  const t = useT();
  const groups = grouping && grouping.boards.length > 0 ? groupTracked(items, grouping) : null;
  return (
    <section aria-labelledby="tracked-items" className="space-y-4">
      <div className="section-head">
        <h2 id="tracked-items" className="section-title">
          {t("today.tracked.heading")}
        </h2>
        {items.length > 0 && (
          <span className="mono tnum text-[11px] text-faint">{items.length}</span>
        )}
        <span aria-hidden="true" className="section-rule" />
        {controls}
      </div>
      {items.length === 0 ? (
        (empty ?? null)
      ) : (
        <>
          <p className="max-w-[65ch] text-xs text-faint">{t("today.tracked.note")}</p>
          {groups === null ? (
            <ul className="row-list">
              {items.map((item) => (
                <li key={item.id} className="flex items-start justify-between gap-4">
                  <TrackedItemLite item={item} />
                </li>
              ))}
            </ul>
          ) : (
            <div className="space-y-6">
              {groups.map((group) => (
                <section
                  key={group.key}
                  aria-label={group.name ?? t("tracked.group.noBoard")}
                  className="space-y-2.5"
                >
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                    <h3 className="text-[13px] font-semibold text-ink">
                      {group.name ?? t("tracked.group.noBoard")}
                    </h3>
                    {stats && <GroupStats items={group.items} />}
                  </div>
                  {group.modules.map((mod) => (
                    <div key={mod.key} className="space-y-2">
                      {mod.name && <h4 className="text-xs text-faint">{mod.name}</h4>}
                      <ul className="row-list">
                        {mod.items.map((item) => (
                          <li key={item.id} className="flex items-start justify-between gap-4">
                            <TrackedItemLite item={item} />
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </section>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

// --- Today's read surface -----------------------------------------------------

/** A stable hue per source, drawn from the token layer's six category colors.
 * Colour carries source identity here — the same source always reads the same,
 * which is what makes a long day scannable. It never encodes importance. */
const SOURCE_HUES = [
  "--cat-policy",
  "--cat-sector",
  "--cat-ma",
  "--cat-earnings",
  "--cat-rumor",
  "--cat-other",
] as const;

function sourceHue(key: string): string {
  let h = 2166136261;
  for (let i = 0; i < key.length; i += 1) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return SOURCE_HUES[(h >>> 0) % SOURCE_HUES.length];
}

/** What the item IS, from how its text was obtained — a podcast, a video, a PDF
 * report and an OCR'd image note are different objects and should not all render
 * as the same paragraph. */
type ItemKind = "audio" | "video" | "report" | "image" | "feed" | "article";

function itemKind(item: TrackedItemCard): ItemKind {
  switch (item.extraction_method) {
    case "whisper":
      return "audio";
    case "caption":
      return "video";
    case "pdf_text":
      return "report";
    case "frame_ocr":
      return "image";
    case "feed_summary":
      return "feed";
    default:
      return "article";
  }
}

const KIND_LABEL: Record<ItemKind, string> = {
  audio: "itemkind.audio",
  video: "itemkind.video",
  report: "itemkind.report",
  image: "itemkind.image",
  feed: "itemkind.feed",
  article: "itemkind.article",
};

/** The source's mark: its initial on its own hue. Gives the left margin a
 * scannable identity column instead of nothing. */
function SourceMark({ label, hue }: { label: string; hue: string }) {
  return (
    <span
      aria-hidden="true"
      style={{
        color: `rgb(var(${hue}))`,
        background: `rgb(var(${hue}) / 0.12)`,
        borderColor: `rgb(var(${hue}) / 0.32)`,
      }}
      className="mono inline-flex h-6 w-6 shrink-0 items-center justify-center rounded border text-[11px] font-medium uppercase"
    >
      {label.slice(0, 1)}
    </span>
  );
}

/** A few bars standing in for a waveform — audio and video items get a shape of
 * their own so the page is not one paragraph repeated. Decorative only. */
function WaveMark({ hue }: { hue: string }) {
  const bars = [5, 11, 7, 14, 9, 16, 6, 12, 8];
  return (
    <span aria-hidden="true" className="flex items-end gap-[2px]">
      {bars.map((height, i) => (
        <span
          key={i}
          style={{ height, background: `rgb(var(${hue}) / ${0.35 + (height / 16) * 0.5})` }}
          className="w-[2px] rounded-full"
        />
      ))}
    </span>
  );
}

function KindMark({ kind, hue, label }: { kind: ItemKind; hue: string; label: string }) {
  return (
    <span className="flex items-center gap-2">
      {(kind === "audio" || kind === "video") && <WaveMark hue={hue} />}
      <span
        style={{ color: `rgb(var(${hue}))` }}
        className="mono text-[10px] uppercase tracking-[0.12em]"
      >
        {label}
      </span>
    </span>
  );
}

/** One item. `size` sets how much room it gets: the lead of a day reads large,
 * items with a summary read medium, and anything with no summary (a typed
 * failure, a pending fetch) compresses to a single dense line. Weight follows
 * how much daily actually HAS — never a ranking. */
function TimelineRow({
  item,
  size = "mid",
  undated = false,
}: {
  item: TrackedItemCard;
  size?: "lead" | "mid" | "thin";
  undated?: boolean;
}) {
  const t = useT();
  const intlLocale = useIntlLocale();
  const { locale } = useLocale();
  const status = trackedStatus(item, t);
  const similar = item.similar_count ?? 0;
  const when = new Date(item.published ?? item.first_seen);
  const summary = item.enrichment
    ? locale === "zh"
      ? item.enrichment.summary_zh
      : item.enrichment.summary_en
    : null;
  const tags = item.enrichment?.tags ?? [];
  const sourceLabel = item.source_name || item.domain || "?";
  const hue = sourceHue(sourceLabel);
  const kind = itemKind(item);
  const title = trackedTitle(item, locale) ?? item.url ?? t("today.tracked.untitled");
  const time = undated
    ? "—"
    : when.toLocaleTimeString(intlLocale, { hour: "2-digit", minute: "2-digit", hour12: false });

  if (size === "thin") {
    return (
      <li className="group/item flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2.5 transition-opacity group-hover/day:opacity-45 hover:!opacity-100">
        <span className="mono tnum w-10 shrink-0 text-[11px] text-faint">{time}</span>
        <span style={{ color: `rgb(var(${hue}))` }} className="w-24 shrink-0 truncate text-[11px]">
          {sourceLabel}
        </span>
        {item.tier && (
          <span className="shrink-0 rounded border border-line px-1.5 py-px text-[10px] font-medium text-faint">
            {t(TIER_KEY[item.tier])}
          </span>
        )}
        <Link
          href={`/items/${item.id}`}
          className="min-w-0 flex-1 truncate text-[14px] text-ink transition-colors hover:text-accent"
        >
          {title}
        </Link>
        {!summary && item.status === "fetched" && (
          <span className="text-[11px] italic text-faint">{t("tracked.summary.pending")}</span>
        )}
        {similar > 0 && (
          <span className="shrink-0 text-[11px] text-faint">
            {similar === 1
              ? t("tracked.similar", { count: similar })
              : t("tracked.similar_plural", { count: similar })}
          </span>
        )}
        {status && <span className="text-[11px] italic text-faint">{status}</span>}
        {/* the original stays reachable from every row, however compressed */}
        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] text-accent underline underline-offset-2 transition-colors hover:text-accent-strong"
          >
            {t("tracked.original")}
          </a>
        )}
      </li>
    );
  }

  const lead = size === "lead";
  return (
    <li className="group/item py-5 transition-opacity duration-300 group-hover/day:opacity-45 hover:!opacity-100">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <SourceMark label={sourceLabel} hue={hue} />
        <span style={{ color: `rgb(var(${hue}))` }} className="text-[12px] font-medium">
          {sourceLabel}
        </span>
        <KindMark kind={kind} hue={hue} label={t(KIND_LABEL[kind])} />
        <span className="mono tnum text-[11px] text-faint">{time}</span>
        {item.tier && (
          <span className="rounded border border-line px-1.5 py-px text-[10px] font-medium text-faint">
            {t(TIER_KEY[item.tier])}
          </span>
        )}
      </div>
      <p
        className={`serif mt-2 break-words font-semibold tracking-[-0.012em] text-ink ${
          lead ? "text-[clamp(1.4rem,3.1vw,2rem)] leading-[1.18]" : "text-[19px] leading-[1.28]"
        }`}
      >
        <Link href={`/items/${item.id}`} className="transition-colors hover:text-accent">
          {title}
        </Link>
      </p>
      {summary ? (
        <p
          className={`mt-2.5 max-w-[68ch] leading-[1.75] text-muted ${
            lead ? "text-[14.5px]" : "line-clamp-3 text-[13px]"
          }`}
        >
          <span className="badge mr-1.5 bg-panel text-faint">{t("digest.ai.label")}</span>
          {summary}
        </p>
      ) : (
        item.status === "fetched" && (
          <p className="mt-2 text-[13px] italic text-faint">{t("tracked.summary.pending")}</p>
        )
      )}
      <div className="mt-3 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-faint">
        {tags.slice(0, lead ? 4 : 2).map((tag) => (
          <span key={tag} className="rounded bg-panel px-2 py-0.5 text-muted">
            {tag}
          </span>
        ))}
        {similar > 0 && (
          <span>
            {similar === 1
              ? t("tracked.similar", { count: similar })
              : t("tracked.similar_plural", { count: similar })}
          </span>
        )}
        {status && <span className="italic">{status}</span>}
        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="text-accent underline underline-offset-2 transition-colors hover:text-accent-strong"
          >
            {t("tracked.original")}
          </a>
        )}
      </div>
    </li>
  );
}

/** The chronological reading surface: strictly newest-first, grouped under
 * serif day dividers, timestamps in the margin. Pure presentation over the same
 * tracked cards — no score, no ranking (reverse-chronological only). */
export function TrackedTimeline({ items }: { items: TrackedItemCard[] }) {
  const t = useT();
  const intlLocale = useIntlLocale();
  // undated items would all read as "today" and drown the real chronology, so they
  // fold. Includes typed failures (also undated); they stay listed with their
  // status inside the fold — never dropped (v0.13).
  const isUndated = (i: TrackedItemCard) => !i.published;
  const primary = items.filter((i) => !isUndated(i));
  const undated = items.filter(isUndated);
  const sorted = [...primary].sort((a, b) =>
    (b.published ?? b.first_seen).localeCompare(a.published ?? a.first_seen),
  );
  const days: { day: string; items: TrackedItemCard[] }[] = [];
  for (const item of sorted) {
    const day = new Date(item.published ?? item.first_seen).toLocaleDateString(intlLocale, {
      dateStyle: "long",
    });
    const last = days.at(-1);
    if (last && last.day === day) last.items.push(item);
    else days.push({ day, items: [item] });
  }
  return (
    <div className="space-y-8">
      {undated.length > 0 && (
        <details className="group border-b border-line pb-4">
          <summary className="serif flex cursor-pointer list-none items-baseline gap-3 text-[15px] font-semibold text-ink [&::-webkit-details-marker]:hidden">
            <span>{t("today.undated.heading", { count: undated.length })}</span>
            <span aria-hidden="true" className="h-px flex-1 self-center bg-line" />
            <span
              aria-hidden="true"
              className="text-[11px] font-normal text-faint transition-transform group-open:rotate-180"
            >
              ▾
            </span>
          </summary>
          <p className="mt-2 max-w-[65ch] text-[11px] leading-relaxed text-faint">
            {t("today.undated.note")}
          </p>
          <ul className="mt-1 divide-y divide-line">
            {undated.map((item) => (
              <TimelineRow key={item.id} item={item} size="thin" undated />
            ))}
          </ul>
        </details>
      )}
      {days.map((group, gi) => {
        // rhythm: the day's first item leads; anything without a summary drops to
        // a dense line; the rest read medium. Order is untouched.
        const hasSummary = (i: TrackedItemCard) => Boolean(i.enrichment);
        return (
          <section
            key={group.day}
            aria-label={group.day}
            className="group/day relative pl-6 sm:pl-8"
          >
            {/* the spine: a rail down the margin with a node per day */}
            <span aria-hidden="true" className="absolute inset-y-0 left-1 w-px bg-line sm:left-2" />
            <span
              aria-hidden="true"
              className="absolute left-0 top-2 h-2 w-2 rounded-full border-[1.5px] border-accent bg-surface sm:left-1"
            />
            <h3 className="serif flex items-baseline gap-3 text-[15px] font-semibold text-ink">
              <span>{group.day}</span>
              <span aria-hidden="true" className="h-px flex-1 self-center bg-line" />
              <span className="mono tnum text-[11px] font-normal text-faint">
                {group.items.length}
              </span>
            </h3>
            <ul className="divide-y divide-line">
              {group.items.map((item, i) => (
                <TimelineRow
                  key={item.id}
                  item={item}
                  size={!hasSummary(item) ? "thin" : gi === 0 && i === 0 ? "lead" : "mid"}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

