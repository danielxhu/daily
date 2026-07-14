"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { ApiError, queryBoards, queryDigest, queryModules } from "@/lib/api";
import { TrackedItemsSection, useTrackedGrouping } from "@/components/TrackedItems";
import { useT } from "@/lib/i18n";
import type { DailyDigest } from "@/types/contract";

interface DigestViewProps {
  // injectable so tests never hit the network
  digestFn?: typeof queryDigest;
  boardsFn?: typeof queryBoards;
  modulesFn?: typeof queryModules;
}

/** The full digest — "what changed in my sources recently". Since the check
 * retirement (M16.1, owner 2026-07-08) the digest is the tracked-items channel:
 * every recent item with its source, tier, date, and cached AI summary. Render
 * never calls an LLM (M14.7 invariant); the verified-fact categories are dormant
 * with the rest of the verification surface. Read-only. */
export function DigestView({
  digestFn = queryDigest,
  boardsFn = queryBoards,
  modulesFn = queryModules,
}: DigestViewProps) {
  const [digest, setDigest] = useState<DailyDigest | null>(null);
  const [error, setError] = useState<string | null>(null);
  // M14.6 (owner): recent view window — default a month, adjustable
  const [windowDays, setWindowDays] = useState(30);
  const t = useT();
  // M16.6: board/module grouping + per-group stats — the AIHOT-informed density,
  // computed in code from the cards (render stays cache-only, zero LLM)
  const grouping = useTrackedGrouping(digest?.tracked ?? [], boardsFn, modulesFn);

  useEffect(() => {
    let active = true;
    setError(null);
    digestFn({ windowDays })
      .then((d) => active && setDigest(d))
      .catch(
        (err) =>
          active &&
          setError(err instanceof ApiError ? err.message : t("digest.errLoad")),
      );
    return () => {
      active = false;
    };
  }, [digestFn, windowDays]);

  const tracked = digest?.tracked ?? [];

  return (
    <div className="space-y-6">
      {error && (
        <p role="alert" className="text-sm text-bad-fg">
          {error}
        </p>
      )}
      {!error && digest === null && (
        <p className="text-sm text-muted">{t("digest.loading")}</p>
      )}
      {digest && (
        <>
          <TrackedItemsSection
            items={tracked}
            grouping={grouping}
            stats
            controls={
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
            }
            empty={
              <p className="text-sm text-muted">
                {t("today.briefing.empty").split("{sourcesLink}")[0]}
                <Link href="/tracking" className="text-accent hover:text-accent-strong">
                  {t("today.briefing.sourcesLinkText")}
                </Link>
                {t("today.briefing.empty").split("{sourcesLink}")[1]}
              </p>
            }
          />
        </>
      )}
    </div>
  );
}
