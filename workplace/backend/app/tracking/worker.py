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

Classes 2/3 get a FEW attempts per app run per item, spaced by a cooldown
(2026-07-19: bilibili's 412/SSL blocks are TEMPORARY — one-attempt-per-process
meant "自动出现" was a lie until the next restart; but anti-bot sites still must
not be hammered every 30 seconds). A manual refresh resets the item's budget —
opening its page is an explicit retry request. Class 1 gets two tries (an LLM
outage mid-run shouldn't permanently skip items). Every item is processed under
the poll mutex, non-blocking: while a poll or a manual refresh runs, the tick
simply skips — nothing ever interleaves.
"""

from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

from app.clients.base import LLMClient
from app.db.subscription_store import purge_orphaned_items
from app.db.tracked_item_store import set_item_enrichment
from app.ingestion.domains import normalize_domain
from app.ingestion.ingest import IngestFn
from app.knowledge.semantic import SemanticIndex
from app.tracking.domain_backoff import blocked_until
from app.tracking.refresh import RefreshError, RefreshFailedError, refresh_item
from app.tracking.runtime import _POLL_MUTEX
from app.tracking.summarize import enrich_fetched_item

_SUMMARY_BATCH = 4
_FETCH_BATCH = 2
_TRANSCRIBE_BATCH = 1

# per-app-run attempt bookkeeping — never hammer a blocked site tick after tick,
# but retry a few times with a cooldown (temporary blocks lift on their own).
# The cooldown ESCALATES (2026-07-21 audit: a fixed 10-minute clock burned the
# whole budget inside one hour-scale bilibili risk-control window — four shots
# at the same locked door): 10 min, then 1 h, then 6 h between attempts.
_fetch_attempts: dict[str, int] = {}
_fetch_next_try: dict[str, float] = {}
_FETCH_MAX_TRIES = 4
_RETRY_COOLDOWNS: tuple[float, ...] = (600.0, 3600.0, 21600.0)
_summary_failures: dict[str, int] = {}
_SUMMARY_MAX_TRIES = 2


def reset_attempts(item_id: str) -> None:
    """A manual refresh is an explicit retry request — give this item a fresh
    per-run attempt budget so the worker picks it up on the next tick."""
    _fetch_attempts.pop(item_id, None)
    _fetch_next_try.pop(item_id, None)


def work_once(
    conn: sqlite3.Connection,
    *,
    llm: LLMClient,
    ingest: IngestFn,
    transcribe_ingest: IngestFn,
    semantic_index: SemanticIndex | None = None,
) -> dict[str, int]:
    """One bounded pass over the pending backlog; returns per-class counts.
    Safe to call every few seconds — every wave holds the poll mutex and skips
    outright when a poll / manual refresh is running."""
    counts = {"summarized": 0, "fetched": 0, "transcribed": 0, "indexed": 0}

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
        "SELECT id, url FROM tracked_items"
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
        "SELECT id, url FROM tracked_items"
        " WHERE status = 'deferred' AND enrichment IS NULL AND url IS NOT NULL"
        " ORDER BY first_seen DESC",
        limit=_TRANSCRIBE_BATCH,
        llm=llm,
        ingest=transcribe_ingest,
    )

    # -- class 4: semantic index upkeep (owner 2026-07-21) — a few entries per
    # tick until every enriched item + saved note is embedded; fails soft ------
    if semantic_index is not None:
        counts["indexed"] = semantic_index.index_pending(conn)
    return counts


def _refresh_batch(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
    llm: LLMClient,
    ingest: IngestFn,
) -> int:
    """Refresh up to `limit` eligible items through the shared manual path
    (mutex-honest, typed failures). A failure spends one of the item's bounded
    attempts and starts its cooldown — the backlog never wedges on one hostile
    site, and a temporarily-blocked site gets another chance later."""
    from app.tracking.runtime import PollInProgressError

    done = 0
    now = time.monotonic()
    for row in conn.execute(query).fetchall():
        if done >= limit:
            break
        item_id = str(row["id"])
        # domain frozen by risk control → not this item's fault: skip WITHOUT
        # consuming an attempt; the item wakes up when the domain thaws
        if blocked_until(conn, normalize_domain(row["url"])) is not None:
            continue
        attempts = _fetch_attempts.get(item_id, 0)
        if attempts >= _FETCH_MAX_TRIES:
            continue
        if now < _fetch_next_try.get(item_id, 0.0):
            continue
        _fetch_attempts[item_id] = attempts + 1
        cooldown = _RETRY_COOLDOWNS[min(attempts, len(_RETRY_COOLDOWNS) - 1)]
        _fetch_next_try[item_id] = now + cooldown
        try:
            refresh_item(conn, item_id, llm=llm, ingest=ingest)
            done += 1
        except PollInProgressError:
            # not this item's fault — refund the attempt and retry next tick
            _fetch_attempts[item_id] -= 1
            _fetch_next_try.pop(item_id, None)
            break
        except (RefreshError, RefreshFailedError):
            continue  # typed + already visible on the item; cooldown then retry
    return done
