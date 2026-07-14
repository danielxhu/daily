"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { Reveal } from "@/components/Reveal";
import { TrackedTimeline, useTrackedGrouping } from "@/components/TrackedItems";
import {
  ApiError,
  adoptSourcePack,
  pollNow,
  queryBoards,
  queryDigest,
  queryModules,
  querySubscriptions,
} from "@/lib/api";
import { useIntlLocale, useT } from "@/lib/i18n";
import type { DailyDigest, Subscription } from "@/types/contract";

interface TodayViewProps {
  // injectable so tests never hit the network
  digestFn?: typeof queryDigest;
  subscriptionsFn?: typeof querySubscriptions;
  adoptFn?: typeof adoptSourcePack;
  pollFn?: typeof pollNow;
  // M16.6: board/module names for the grouped briefing
  boardsFn?: typeof queryBoards;
  modulesFn?: typeof queryModules;
}

/** Today dashboard (home). The first screen answers "what should I look at today?" —
 * what your tracked sources published recently, what needs attention, and the
 * health of your sources. The verified-fact briefing left the surface with the
 * check retirement (M16.1, owner 2026-07-08); tracked items ARE the briefing now. */
export function TodayView({
  digestFn = queryDigest,
  subscriptionsFn = querySubscriptions,
  adoptFn = adoptSourcePack,
  pollFn = pollNow,
  boardsFn = queryBoards,
  modulesFn = queryModules,
}: TodayViewProps) {
  const [digest, setDigest] = useState<DailyDigest | null>(null);
  const [subs, setSubs] = useState<Subscription[] | null>(null);
  // AIHOT-style board filter (owner 2026-07-10): null = all boards
  const [boardTab, setBoardTab] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  // M14.6 (owner): the briefing shows RECENT changes — default a month, adjustable
  const [windowDays, setWindowDays] = useState(30);
  const adoptTried = useRef(false); // once per mount; the backend flag is the real gate
  // M14.4 review fix: the seeding flow must survive its OWN effect's cleanup — the
  // interval refresh writes `subs`, which re-runs the effect; an effect-scoped
  // `active` flag would then abort the final refresh and leave "polling…" stuck
  // forever. Lifecycle is tied to the COMPONENT (mountedRef), not the effect pass.
  const mountedRef = useRef(true);
  const seedTickerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const windowRef = useRef(windowDays);
  const t = useT();
  const intlLocale = useIntlLocale();
  // M16.6: board/module names for the grouped briefing (before any early return —
  // hooks are unconditional; the hook itself no-ops while there are no items)
  const grouping = useTrackedGrouping(digest?.tracked ?? [], boardsFn, modulesFn);

  useEffect(() => {
    windowRef.current = windowDays;
  }, [windowDays]);

  useEffect(
    () => () => {
      mountedRef.current = false;
      if (seedTickerRef.current) clearInterval(seedTickerRef.current);
    },
    [],
  );

  useEffect(() => {
    let active = true;
    Promise.all([digestFn({ windowDays }), subscriptionsFn()])
      .then(([d, s]) => {
        if (!active) return;
        setDigest(d);
        setSubs(s);
      })
      .catch(
        (err) =>
          active &&
          setError(err instanceof ApiError ? err.message : t("today.errLoad")),
      );
    return () => {
      active = false;
    };
  }, [digestFn, subscriptionsFn, windowDays]);

  // Day-1 auto-fill (M14.1, owner 2026-07-06): a cold start (no sources) adopts
  // the STATIC starter pack and runs one first poll — the user trims afterwards.
  // seeded=false means the user deliberately emptied their list: keep it empty.
  useEffect(() => {
    if (subs === null || subs.length > 0 || adoptTried.current) return;
    adoptTried.current = true;
    void (async () => {
      try {
        const adopted = await adoptFn();
        if (!mountedRef.current || !adopted.seeded) return;
        setSeeding(true);
        // M14.4: content lands incrementally while the first poll runs — refresh
        // the briefing every 15s instead of waiting for the whole poll to finish.
        // Guards use mountedRef (NOT an effect-scoped flag): the refresh writes
        // `subs`, which re-runs this effect, and the flow must keep going.
        const refresh = async () => {
          try {
            const [d, s] = await Promise.all([
              digestFn({ windowDays: windowRef.current }),
              subscriptionsFn(),
            ]);
            if (mountedRef.current) {
              setDigest(d);
              setSubs(s);
            }
          } catch {
            // keep the last good view; the next tick retries
          }
        };
        seedTickerRef.current = setInterval(() => void refresh(), 15_000);
        try {
          await pollFn(); // first poll — bounded by the M13.4 first-poll cap
        } catch {
          // the poll failed; the seeded sources + their health still show below
        } finally {
          if (seedTickerRef.current) clearInterval(seedTickerRef.current);
          seedTickerRef.current = null;
        }
        if (!mountedRef.current) return;
        await refresh();
      } catch {
        // adopt unreachable → keep the plain empty state (nothing was changed)
      } finally {
        if (mountedRef.current) setSeeding(false);
      }
    })();
  }, [subs, adoptFn, pollFn, digestFn, subscriptionsFn]);

  if (error) {
    return (
      <p role="alert" className="text-sm text-bad-fg">
        {error}
      </p>
    );
  }
  if (digest === null || subs === null) {
    return <p className="text-sm text-muted">{t("today.loading")}</p>;
  }

  const tracked = digest.tracked ?? [];
  const filtered = boardTab ? tracked.filter((i) => i.board_id === boardTab) : tracked;
  const unhealthy = subs.filter(needsLook);
  // M16.6 header: today's date + the latest poll across sources. Honest boundary
  // stays in tracking language — polling is periodic, never real-time (§2.2).
  const lastPolled = subs
    .map((s) => s.last_polled)
    .filter((v): v is string => Boolean(v))
    .sort()
    .at(-1);

  return (
    <div className="space-y-8">
      <header
        aria-label={t("today.head.aria")}
        className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line pb-4"
      >
        <p className="text-sm font-medium text-ink">
          {new Date().toLocaleDateString(intlLocale, { dateStyle: "full" })}
        </p>
        <p className="tnum text-xs text-faint">
          {lastPolled
            ? t("today.head.lastPoll", {
                time: new Date(lastPolled).toLocaleString(intlLocale),
              })
            : t("today.head.neverPolled")}
          {" · "}
          {t("today.head.pollNote")}
        </p>
      </header>
      {seeding && (
        <p role="status" className="text-sm text-muted">
          {t("today.seeding")}
        </p>
      )}
      <Reveal index={0}>
        <section aria-labelledby="tracked-items" className="space-y-4">
          <div className="section-head">
            <h2 id="tracked-items" className="section-title">
              {t("today.tracked.heading")}
            </h2>
            {tracked.length > 0 && (
              <span className="mono tnum text-[11px] text-faint">{tracked.length}</span>
            )}
            <span aria-hidden="true" className="section-rule" />
            <select
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
              aria-label={t("digest.window.aria")}
              className="rounded-lg border border-line bg-panel px-2 py-1 text-xs text-muted"
            >
              {[7, 30, 90].map((days) => (
                <option key={days} value={days}>
                  {t("digest.window.option", { days })}
                </option>
              ))}
            </select>
            <Link href="/digest" className="text-xs text-faint transition-colors hover:text-muted">
              {t("today.briefing.fullDigest")}
            </Link>
          </div>
          {tracked.length === 0 ? (
            <p className="text-sm text-muted">
              {t("today.briefing.empty").split("{sourcesLink}")[0]}
              <Link href="/tracking" className="text-accent hover:text-accent-strong">
                {t("today.briefing.sourcesLinkText")}
              </Link>
              {t("today.briefing.empty").split("{sourcesLink}")[1]}
            </p>
          ) : (
            <>
              <p className="max-w-[65ch] text-xs text-faint">{t("today.tracked.note")}</p>
              {(grouping?.boards.length ?? 0) > 0 && (
                <div
                  role="group"
                  aria-label={t("today.tabs.aria")}
                  className="flex flex-wrap gap-1.5"
                >
                  <BoardTab
                    label={t("today.tabs.all")}
                    active={boardTab === null}
                    onClick={() => setBoardTab(null)}
                  />
                  {(grouping?.boards ?? []).map((board) => (
                    <BoardTab
                      key={board.id}
                      label={board.name}
                      active={boardTab === board.id}
                      onClick={() => setBoardTab(board.id)}
                    />
                  ))}
                </div>
              )}
              {filtered.length === 0 ? (
                <p className="text-sm text-muted">{t("today.tabs.empty")}</p>
              ) : (
                <TrackedTimeline items={filtered} />
              )}
            </>
          )}
        </section>
      </Reveal>
      <Reveal index={1}>
        <NeedsAttention unhealthy={unhealthy} />
      </Reveal>
      <Reveal index={2}>
        <SourceStatus subs={subs} />
      </Reveal>
    </div>
  );
}

/** One board-filter pill (AIHOT-style tabs, owner 2026-07-10). */
function BoardTab({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded-lg border px-2.5 py-1 text-xs transition-colors ${
        active ? "border-accent bg-panel text-ink" : "border-line text-muted hover:border-muted"
      }`}
    >
      {label}
    </button>
  );
}

/** A source needs a look when it is unhealthy OR has an actionable recorded issue
 * (M13.1): the first `items_unfetchable` failure writes `subscription_failure_kind`
 * + `last_error` while `health` stays "ok" until the §6.6 threshold — Today must
 * never read that as "all healthy" (beta P0-1). A clean poll clears both fields. */
function needsLook(sub: Subscription): boolean {
  return sub.health === "unhealthy" || sub.subscription_failure_kind != null || sub.last_error != null;
}

function NeedsAttention({ unhealthy }: { unhealthy: Subscription[] }) {
  const t = useT();
  return (
    <section aria-labelledby="today-attention" className="space-y-4">
      <div className="section-head">
        <h2 id="today-attention" className="section-title">
          {t("today.attention.heading")}
        </h2>
        {unhealthy.length > 0 && (
          <span className="mono tnum text-[11px] text-warn-fg">{unhealthy.length}</span>
        )}
        <span aria-hidden="true" className="section-rule" />
      </div>
      {unhealthy.length === 0 ? (
        <p className="text-sm text-muted">{t("today.attention.nothing")}</p>
      ) : (
        <ul className="row-list">
          {unhealthy.map((sub) => (
            <li key={sub.id} className="flex items-baseline gap-2.5 text-sm">
              <AttentionDot />
              <p className="min-w-0">
                <span className="font-medium text-warn-fg">
                  {t("today.attention.sourceNeedsLook")}
                </span>{" "}
                <span className="break-words text-muted">{sub.input_url}</span>{" "}
                <span className="text-faint">—</span>{" "}
                <Link
                  href="/tracking"
                  className="text-accent underline-offset-2 hover:text-accent-strong"
                >
                  {t("today.attention.openSources")}
                </Link>
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** A small warn health dot — one of the two places glow is allowed (DESIGN.md §6). */
function AttentionDot() {
  return (
    <span
      aria-hidden="true"
      className="mt-1.5 h-1.5 w-1.5 shrink-0 self-start rounded-full bg-warn-fg"
      style={{ boxShadow: "0 0 8px rgb(var(--warn-fg) / 0.5)" }}
    />
  );
}

function SourceStatus({ subs }: { subs: Subscription[] }) {
  const t = useT();
  const unhealthy = subs.filter(needsLook).length;
  return (
    <section aria-labelledby="today-sources" className="space-y-3">
      <div className="section-head">
        <h2 id="today-sources" className="section-title">
          {t("today.sources.heading")}
        </h2>
        {subs.length > 0 && (
          <span className="mono tnum text-[11px] text-faint">{subs.length}</span>
        )}
        <span aria-hidden="true" className="section-rule" />
        <Link href="/tracking" className="text-xs text-faint transition-colors hover:text-muted">
          {t("today.sources.manage")}
        </Link>
      </div>
      {subs.length === 0 ? (
        <p className="text-sm text-muted">
          {t("today.sources.none").split("{addLink}")[0]}
          <Link href="/tracking" className="text-accent hover:text-accent-strong">
            {t("today.sources.addLinkText")}
          </Link>
          {t("today.sources.none").split("{addLink}")[1]}
        </p>
      ) : (
        <p className="text-sm text-muted">
          {subs.length === 1
            ? t("today.sources.watching", { count: subs.length })
            : t("today.sources.watching_plural", { count: subs.length })}
          {unhealthy > 0 ? (
            <span className="tnum text-warn-fg">{t("today.sources.needLook", { unhealthy })}</span>
          ) : (
            <span className="text-ok-fg">{t("today.sources.allHealthy")}</span>
          )}
          .
        </p>
      )}
    </section>
  );
}
