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

/** The item title in the ACTIVE locale (owner 2026-07-10: the language toggle
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
  if (item.status === "deferred") return t("verify.failure.transcription_deferred");
  if (item.status === "new") return t("today.tracked.processing");
  if (item.degraded_reason) return t("today.tracked.degraded");
  return null;
}

/** One tracked item's lite expression (M15.4, trimmed by M16.1): title +
 * provenance link, AI briefing, then the meta line — domain, code-first tier,
 * date, the dup/repost echo hint, and the typed status. The check surface left
 * the product with M16.1 (owner 2026-07-08): no credibility, no score, no
 * deep-check entry. Shared by Today, the full Digest, and Knowledge search hits
 * so the semantics never drift between surfaces. */
export function TrackedItemLite({ item }: { item: TrackedItemCard }) {
  const t = useT();
  const intlLocale = useIntlLocale();
  const { locale } = useLocale();

  const status = trackedStatus(item, t);
  const when = item.published ?? item.first_seen;
  const similar = item.similar_count ?? 0;
  // M16.3: the bilingual enrichment carries BOTH languages — the toggle switches
  // instantly, no call, no cache miss (owner 2026-07-08). The deprecated
  // single-language `summary` is never consumed (M16.1).
  const summary = item.enrichment
    ? locale === "zh"
      ? item.enrichment.summary_zh
      : item.enrichment.summary_en
    : null;
  return (
    <div className="min-w-0 space-y-1">
      {/* M16.4: the title opens the item's OWN detail page ("点进任何一条信息");
          the original link moves to the meta line below */}
      <p className="break-words text-[15px] font-medium text-ink">
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

// --- AIHOT-style timeline (owner 2026-07-10): Today's read surface ------------

/** One timeline row: time on a left rail, then the card — source line on top
 * (matching the reference screenshots), title, AI summary, tags/status. */
function TimelineRow({ item }: { item: TrackedItemCard }) {
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
  return (
    <li className="grid grid-cols-[3.25rem_auto_1fr] gap-x-3">
      <span className="mono tnum pt-0.5 text-right text-xs text-faint">
        {when.toLocaleTimeString(intlLocale, { hour: "2-digit", minute: "2-digit", hour12: false })}
      </span>
      <span aria-hidden="true" className="relative flex w-3 justify-center">
        <span className="absolute inset-y-0 w-px bg-line" />
        <span className="relative mt-1.5 h-2 w-2 rounded-lg border border-line bg-panel" />
      </span>
      <div className="min-w-0 space-y-1 rounded-lg border border-line bg-panel p-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-faint">
          {item.domain && <span className="mono">{item.domain}</span>}
          {item.tier && (
            <span className="badge bg-surface text-muted">{t(TIER_KEY[item.tier])}</span>
          )}
        </div>
        <p className="break-words text-[15px] font-medium leading-snug text-ink">
          <Link href={`/items/${item.id}`} className="transition-colors hover:text-accent">
            {trackedTitle(item, locale) ?? item.url ?? t("today.tracked.untitled")}
          </Link>
        </p>
        {summary ? (
          // the (now three-paragraph) briefing lives on the detail page — the
          // timeline shows the lede only
          <p className="line-clamp-4 max-w-[72ch] text-xs leading-relaxed text-muted">
            <span className="badge mr-1.5 bg-surface text-faint">{t("digest.ai.label")}</span>
            {summary}
          </p>
        ) : (
          item.status === "fetched" && (
            <p className="text-xs italic text-faint">{t("tracked.summary.pending")}</p>
          )
        )}
        <div className="flex flex-wrap items-center gap-2 text-xs text-faint">
          {tags.map((tag) => (
            <span key={tag} className="badge bg-surface text-muted">
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
      </div>
    </li>
  );
}

/** The AIHOT-style chronological feed (owner 2026-07-10): strictly newest-first,
 * grouped under day headers, a time rail on the left. Pure presentation over the
 * same tracked cards — no score, no featured badge (owner: 都不要). */
export function TrackedTimeline({ items }: { items: TrackedItemCard[] }) {
  const intlLocale = useIntlLocale();
  const sorted = [...items].sort((a, b) =>
    (b.published ?? b.first_seen).localeCompare(a.published ?? a.first_seen),
  );
  const days: { day: string; items: TrackedItemCard[] }[] = [];
  for (const item of sorted) {
    const day = new Date(item.published ?? item.first_seen).toLocaleDateString(intlLocale, {
      dateStyle: "medium",
    });
    const last = days.at(-1);
    if (last && last.day === day) last.items.push(item);
    else days.push({ day, items: [item] });
  }
  return (
    <div className="space-y-5">
      {days.map((group) => (
        <section key={group.day} aria-label={group.day} className="space-y-3">
          <h3 className="tnum text-[13px] font-semibold text-ink">{group.day}</h3>
          <ul className="space-y-3">
            {group.items.map((item) => (
              <TimelineRow key={item.id} item={item} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

