"""Background enrichment worker (owner 2026-07-10: "抓取原文生成综述应该不需要
用户点击直接就可以生成").

While the app runs, pending items upgrade THEMSELVES — no clicks. Each tick
works a small, bounded batch in priority order:

  1. summary-only — stored text but no AI summary: ONE flash call each (fast,
     a few per tick, concurrent);
  2. fetch+summarize — no stored text, has a URL: re-fetch (whisper still
     deferred) + summarize, a couple per tick;
  3. transcribe — deferred audio/video: the full ingest with whisper, ONE per
     tick (CPU-heavy minutes; the heaviest work goes last and never queues up).

Classes 2/3 get ONE attempt per app run per item (anti-bot sites must not be
hammered every 30 seconds; the manual detail-page button remains the retry).
Class 1 gets two tries (an LLM outage mid-run shouldn't permanently skip items).
Every item is processed under the poll mutex, non-blocking: while a poll or a
manual refresh runs, the tick simply skips — nothing ever interleaves.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

from app.clients.base import LLMClient
from app.db.subscription_store import purge_orphaned_items
from app.db.tracked_item_store import set_item_enrichment
from app.ingestion.domains import normalize_domain
from app.ingestion.ingest import IngestFn
from app.tracking.refresh import RefreshError, RefreshFailedError, refresh_item
from app.tracking.runtime import _POLL_MUTEX
from app.tracking.summarize import enrich_fetched_item

_SUMMARY_BATCH = 4
_FETCH_BATCH = 2
_TRANSCRIBE_BATCH = 1

# per-app-run attempt bookkeeping — never hammer a blocked site tick after tick
_fetch_attempted: set[str] = set()
_summary_failures: dict[str, int] = {}
_SUMMARY_MAX_TRIES = 2


def work_once(
    conn: sqlite3.Connection,
    *,
    llm: LLMClient,
    ingest: IngestFn,
    transcribe_ingest: IngestFn,
) -> dict[str, int]:
    """One bounded pass over the pending backlog; returns per-class counts.
    Safe to call every few seconds — every wave holds the poll mutex and skips
    outright when a poll / manual refresh is running."""
    counts = {"summarized": 0, "fetched": 0, "transcribed": 0}

    # self-heal every tick (owner 2026-07-13): items of a deleted source must
    # disappear within seconds, whatever code path did the deleting
    purge_orphaned_items(conn)

    # -- class 1: stored text, missing only its summary (fast, concurrent) -----
    rows = conn.execute(
        "SELECT id, subscription_id, item_key, url, title, content_excerpt"
        " FROM tracked_items"
        " WHERE content_excerpt IS NOT NULL AND enrichment IS NULL"
        " ORDER BY first_seen DESC"
    ).fetchall()
    batch = [r for r in rows if _summary_failures.get(str(r["id"]), 0) < _SUMMARY_MAX_TRIES][
        :_SUMMARY_BATCH
    ]
    if batch:
        if not _POLL_MUTEX.acquire(blocking=False):
            return counts
        try:
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                results = list(
                    pool.map(
                        lambda r: enrich_fetched_item(
                            r["content_excerpt"],
                            title=r["title"],
                            domain=normalize_domain(r["url"]) if r["url"] else None,
                            llm=llm,
                        ),
                        batch,
                    )
                )
            for row, enrichment in zip(batch, results, strict=True):
                if enrichment is None:
                    _summary_failures[str(row["id"])] = _summary_failures.get(str(row["id"]), 0) + 1
                    continue
                set_item_enrichment(
                    conn,
                    subscription_id=row["subscription_id"],
                    item_key=row["item_key"],
                    enrichment=enrichment,
                )
                counts["summarized"] += 1
        finally:
            _POLL_MUTEX.release()

    # -- class 2: no stored text yet — re-fetch + summarize (one attempt/run) --
    counts["fetched"] = _refresh_batch(
        conn,
        "SELECT id FROM tracked_items"
        " WHERE content_excerpt IS NULL AND enrichment IS NULL AND url IS NOT NULL"
        " AND status IN ('new', 'fetched', 'failed')"
        " ORDER BY first_seen DESC",
        limit=_FETCH_BATCH,
        llm=llm,
        ingest=ingest,
    )

    # -- class 3: deferred audio/video — transcribe, ONE per tick --------------
    counts["transcribed"] = _refresh_batch(
        conn,
        "SELECT id FROM tracked_items"
        " WHERE status = 'deferred' AND enrichment IS NULL AND url IS NOT NULL"
        " ORDER BY first_seen DESC",
        limit=_TRANSCRIBE_BATCH,
        llm=llm,
        ingest=transcribe_ingest,
    )
    return counts


def _refresh_batch(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
    llm: LLMClient,
    ingest: IngestFn,
) -> int:
    """Refresh up to `limit` not-yet-attempted items through the shared manual
    path (mutex-honest, typed failures). A failure marks the item attempted for
    this app run and moves on — the backlog never wedges on one hostile site."""
    from app.tracking.runtime import PollInProgressError

    done = 0
    for row in conn.execute(query).fetchall():
        if done >= limit:
            break
        item_id = str(row["id"])
        if item_id in _fetch_attempted:
            continue
        _fetch_attempted.add(item_id)
        try:
            refresh_item(conn, item_id, llm=llm, ingest=ingest)
            done += 1
        except PollInProgressError:
            _fetch_attempted.discard(item_id)  # not this item's fault — retry later
            break
        except (RefreshError, RefreshFailedError):
            continue  # typed + already visible on the item; manual retry exists
    return done
