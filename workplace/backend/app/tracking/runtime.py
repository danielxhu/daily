"""Tracking poll runtime (SSOT §6.2–§6.6 / FR-3; verification engine removed
2026-07-13 by owner decision — "把所有旧代码全部删去").

The wire that turns subscriptions from CRUD rows into a live habit loop: discover
each subscription's new items, fetch their content, persist the excerpt, and
generate the bilingual AI enrichment — nothing else. One `run_poll` call =

  1. `poll_all` — fetch each feed/homepage/platform listing, dedup, queue new
     item URLs (per-source isolation: one broken source never blocks the others,
     §6.6);
  2. per subscription, fetch the new items concurrently (whisper transcription
     never runs inside a poll — caption-less audio/video lands as a typed
     `transcription_deferred` item; the background worker / detail page
     transcribes on demand), persist excerpts, settle typed statuses, and brief
     each fetched item bilingually;
  3. `apply_poll_health` — classify failures + back off (or raise one anomaly);
  4. a `PipelineRun(trigger="poll")` debug trace.

Everything that touches the network is **injected** (`fetch`, `llm`, `ingest`),
so the whole runtime is offline-testable (NFR-3). Both the manual
`POST /tracking/poll` endpoint and the in-process scheduler call `run_poll`.
"""

from __future__ import annotations

import sqlite3
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.clients.base import LLMClient
from app.core.config import PROMPT_VERSION
from app.db.run_trace import RunTrace
from app.db.subscription_store import list_subscriptions, purge_orphaned_items
from app.db.tracked_item_store import (
    set_item_enrichment,
    set_item_excerpt,
    set_status_by_url,
)
from app.ingestion.ingest import IngestFn
from app.schemas.models import (
    IngestionResult,
    ItemEnrichment,
    NormalizedSource,
    Schema,
    SourceFailureKind,
    SourceRequest,
    StepTrace,
    Subscription,
    SubscriptionFailureKind,
)
from app.tracking.health import (
    apply_poll_health,
    classify_subscription_failure,
    subscription_next_action,
)
from app.tracking.poll import Fetch, PollOutcome, poll_all
from app.tracking.summarize import enrich_fetched_item

MAX_ITEM_FAILURES_LISTED = 10  # per subscription, the report lists at most this many

# M14.4 (real-mode finding): a second poll started while one is running sees every
# item already marked seen and reports a misleading "checked N sources · 0 new" —
# and the two contend on SQLite + DeepSeek. ONE poll at a time per process; callers
# surface "a source poll is already running" honestly instead.
_POLL_MUTEX = threading.Lock()


class PollInProgressError(RuntimeError):
    """A poll is already running in this process (surfaced as HTTP 409)."""


class PollItemFailure(Schema):
    """One new item that failed ingestion during a poll (M13.1, beta P0-1) — the
    typed per-item failure. Response-only."""

    url: str | None
    kind: SourceFailureKind
    next_action: str | None = None


class PollSubReport(Schema):
    """One subscription's poll outcome (response-only, not a §7 contract type)."""

    subscription_id: str
    input_url: str
    ok: bool
    new_items: int
    # M13.1: per-item ingestion outcomes — a feed can poll fine while every listed
    # article fails to fetch (anti-bot); that must never read as "all ok" (§6.6).
    items_ok: int = 0
    items_failed: int = 0
    item_failures: list[PollItemFailure] = []  # bounded; items_failed has the total
    # M13.4: older items skipped for good on a FIRST poll (capped to the latest few)
    backlog_skipped: int = 0
    # audio/video items whose transcription is deferred (typed delayed processing,
    # NOT counted as failed) — the background worker / detail page transcribes.
    items_deferred: int = 0
    failure_kind: SubscriptionFailureKind | None = None
    next_action: str | None = None  # user-facing next step on failure (§6.6)
    error: str | None = None


class PollReport(Schema):
    """The manual poll's useful counts + per-subscription errors (response-only)."""

    run_id: str
    polled: int
    new_items: int
    system_anomaly: bool  # a broad simultaneous failure was detected (§6.6)
    subscriptions: list[PollSubReport]


def _ingest_only(
    reqs: list[SourceRequest], *, ingest: IngestFn
) -> tuple[list[NormalizedSource], list[IngestionResult]]:
    """Fetch a subscription's new items concurrently — no LLM here.
    Returns (ok sources re-keyed to unique ids, typed failed results)."""
    with ThreadPoolExecutor(max_workers=min(8, len(reqs))) as pool:
        results = list(pool.map(ingest, reqs))
    sources: list[NormalizedSource] = []
    failed: list[IngestionResult] = []
    for r in results:
        if r.status == "ok" and r.source is not None:
            sources.append(r.source.model_copy(update={"source_id": f"trk-{uuid4().hex}"}))
        else:
            failed.append(r)
    return sources, failed


def _summarize_new_items(
    conn: sqlite3.Connection,
    o: PollOutcome,
    sub: Subscription,
    *,
    contents: list[NormalizedSource],
    llm: LLMClient,
) -> int:
    """Generate the poll-time bilingual enrichment for each fetched item (M15.2,
    bilingual since M16.3). The content excerpt is persisted FIRST for every
    target (code-only — discussion/re-enrich grounding survives even a dead LLM),
    then concurrent flash calls fill the enrichment. Returns how many were
    written."""
    targets = [
        (s, o.dispatched_keys[s.url])
        for s in contents
        if s.url is not None and s.url in o.dispatched_keys and s.raw_text
    ]
    if not targets:
        return 0
    titles: dict[str, str | None] = {}
    for src, key in targets:
        set_item_excerpt(
            conn,
            subscription_id=sub.id,
            item_key=key,
            text=src.raw_text,
            method=src.extraction_method,
        )
        # the feed-side title lives on the tracked row; read it BEFORE the pool
        # (one sqlite connection must not cross threads)
        row = conn.execute(
            "SELECT title FROM tracked_items WHERE subscription_id = ? AND item_key = ?",
            (sub.id, key),
        ).fetchone()
        titles[key] = row["title"] if row else None

    def brief(t: tuple[NormalizedSource, str]) -> ItemEnrichment | None:
        return enrich_fetched_item(
            t[0].raw_text, title=titles.get(t[1]), domain=t[0].domain, llm=llm
        )

    if len(targets) == 1:
        results = [brief(targets[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(6, len(targets))) as pool:
            results = list(pool.map(brief, targets))
    written = 0
    for (_, key), enrichment in zip(targets, results, strict=True):
        if enrichment is not None:
            set_item_enrichment(conn, subscription_id=sub.id, item_key=key, enrichment=enrichment)
            written += 1
    return written


def _item_failure_summary(failed: list[IngestionResult], total: int) -> str:
    """One honest line for the report/trace/subscription row: how many of the new
    items failed and with which typed kinds (e.g. '20/20 new items failed: anti_bot ×20')."""
    kinds = Counter(r.failure.kind for r in failed if r.failure is not None)
    kinds_str = ", ".join(f"{kind} ×{n}" for kind, n in kinds.most_common())
    return f"{len(failed)}/{total} new items failed ingestion: {kinds_str}"


def _settle_tracked_items(
    conn: sqlite3.Connection,
    o: PollOutcome,
    sub: Subscription,
    *,
    sources: list[NormalizedSource],
    failed: list[IngestionResult],
    deferred: list[IngestionResult],
    now: datetime,
) -> None:
    """Write each discovered item's own lifecycle status (M15.1a). The row already
    exists from dispatch; nothing here ever deletes it — an item that failed
    anywhere stays visible with a typed reason instead of vanishing."""

    def key_for(url: str | None) -> str | None:
        return o.dispatched_keys.get(url or "")

    for s in sources:  # fetched fine
        key = key_for(s.url)
        if key is not None:
            set_status_by_url(conn, subscription_id=sub.id, item_key=key, status="fetched", now=now)
    for r in deferred:  # audio/video awaiting on-demand transcription
        key = key_for((r.failure.requested_url if r.failure else None) or r.requested.url)
        if key is not None:
            set_status_by_url(
                conn,
                subscription_id=sub.id,
                item_key=key,
                status="deferred",
                failure_kind="transcription_deferred",
                now=now,
            )
    for r in failed:
        failed_url = (r.failure.requested_url if r.failure else None) or r.requested.url
        key = key_for(failed_url)
        if key is not None and r.failure is not None:
            set_status_by_url(
                conn,
                subscription_id=sub.id,
                item_key=key,
                status="failed",
                failure_kind=r.failure.kind,
                now=now,
            )


def run_poll(
    conn: sqlite3.Connection,
    *,
    llm: LLMClient,
    fetch: Fetch,
    ingest: IngestFn,
    ingest_first: IngestFn | None = None,
    subscriptions: list[Subscription] | None = None,
    now: datetime | None = None,
) -> PollReport:
    """Poll every subscription (or the given list): discover, fetch, excerpt,
    status, bilingual briefing. Returns useful per-subscription counts/errors and
    records one `PipelineRun`. Raises `PollInProgressError` when a poll is
    already running (M14.4) — the manual endpoint answers 409 and the scheduler
    tick simply skips. `ingest_first` is the transcription-deferring ingest used
    for EVERY poll when provided (whisper never runs inside a poll)."""
    if not _POLL_MUTEX.acquire(blocking=False):
        raise PollInProgressError("a source poll is already running — try again in a moment")
    try:
        return _run_poll_locked(
            conn,
            llm=llm,
            fetch=fetch,
            ingest=ingest,
            ingest_first=ingest_first,
            subscriptions=subscriptions,
            now=now,
        )
    finally:
        _POLL_MUTEX.release()


def _run_poll_locked(
    conn: sqlite3.Connection,
    *,
    llm: LLMClient,
    fetch: Fetch,
    ingest: IngestFn,
    ingest_first: IngestFn | None = None,
    subscriptions: list[Subscription] | None = None,
    now: datetime | None = None,
) -> PollReport:
    now = now or datetime.now(UTC)
    subs = subscriptions if subscriptions is not None else list_subscriptions(conn)
    sub_by_id = {s.id: s for s in subs}

    # Phase 1 — discover new items (network = injected `fetch`); dedup + mark-seen
    # and per-subscription isolation live in `poll_all`/`poll_subscription`.
    queued: dict[str, list[SourceRequest]] = {}

    def dispatch(sub: Subscription, req: SourceRequest) -> None:
        queued.setdefault(sub.id, []).append(req)

    # self-healing (2026-07-10): items orphaned by source deletions made before
    # the cascade existed (or by an older build) must never linger in Today
    purge_orphaned_items(conn)

    outcomes = poll_all(conn, fetch=fetch, dispatch=dispatch, subscriptions=subs)

    trace = RunTrace(
        conn,
        trigger="poll",
        inputs=[SourceRequest(kind="url", url=s.input_url) for s in subs],
        prompt_version=PROMPT_VERSION,
    )

    # Phase 2 — per subscription: fetch + excerpt + status + bilingual briefing.
    reports: list[PollSubReport] = []
    for o in outcomes:
        sub = sub_by_id[o.subscription_id]
        # 2026-07-10 (owner "轮询好慢"): EVERY poll uses the fast ingest — captions
        # process normally, local whisper transcription never runs inside a poll.
        use_ingest = ingest_first if ingest_first is not None else ingest
        report = _process_outcome(
            conn,
            o,
            sub,
            queued.get(o.subscription_id, []),
            trace=trace,
            llm=llm,
            ingest=use_ingest,
            now=now,
        )
        reports.append(report)

    # Phase 3 — health: classify + back off per source, or raise ONE system anomaly
    # (broad simultaneous failure) and leave every subscription untouched (§6.6).
    item_failed = {
        r.subscription_id: r.error or "" for r in reports if r.failure_kind == "items_unfetchable"
    }
    anomaly = apply_poll_health(conn, outcomes, item_failures=item_failed)

    trace.finish()

    return PollReport(
        run_id=trace.run_id,
        polled=len(subs),
        new_items=sum(r.new_items for r in reports),
        system_anomaly=anomaly is not None,
        subscriptions=reports,
    )


def _is_due(sub: Subscription, now: datetime) -> bool:
    """A subscription is due when it has never been polled, or its own interval has
    elapsed since the last poll. Reading `interval_minutes` fresh from the DB each
    tick is what honors §6.6 backoff (a failing source's doubled interval applies)."""
    if sub.last_polled is None:
        return True
    return sub.last_polled + timedelta(minutes=sub.interval_minutes) <= now


def poll_due_subscriptions(
    conn: sqlite3.Connection,
    *,
    llm: LLMClient,
    fetch: Fetch,
    ingest: IngestFn,
    ingest_first: IngestFn | None = None,
    now: datetime | None = None,
) -> PollReport | None:
    """The scheduler tick: poll only the subscriptions whose interval has elapsed.
    Re-reads the CURRENT active subscriptions from the DB every tick, so sources
    added or removed after startup are handled without a restart (FR-3 / §6.4).
    Returns None when nothing is due (no empty PipelineRun is recorded)."""
    now = now or datetime.now(UTC)
    # self-heal FIRST and unconditionally (owner 2026-07-13: with every source
    # deleted there is nothing "due", so a purge gated behind run_poll never ran
    # and deleted sources' items kept showing in Today)
    purge_orphaned_items(conn)
    due = [s for s in list_subscriptions(conn) if _is_due(s, now)]
    if not due:
        return None
    try:
        return run_poll(
            conn,
            llm=llm,
            fetch=fetch,
            ingest=ingest,
            ingest_first=ingest_first,
            subscriptions=due,
            now=now,
        )
    except PollInProgressError:
        return None  # a manual check is running — this tick just skips (M14.4)


def _process_outcome(
    conn: sqlite3.Connection,
    o: PollOutcome,
    sub: Subscription,
    reqs: list[SourceRequest],
    *,
    trace: RunTrace,
    llm: LLMClient,
    ingest: IngestFn,
    now: datetime,
) -> PollSubReport:
    """Trace + settle + brief this subscription's new items. A fetch/parse failure
    is a typed `ingestion` skip with the user-facing next step."""
    if not o.ok:
        kind = classify_subscription_failure(o.exc) if o.exc is not None else "network"
        trace.record(
            StepTrace(
                step="ingestion",
                status="failed",
                fallback_used=kind,
                counts={"subscription": sub.id, "new_items": 0},
                error=o.error,
            )
        )
        return PollSubReport(
            subscription_id=sub.id,
            input_url=sub.input_url,
            ok=False,
            new_items=0,
            failure_kind=kind,
            next_action=subscription_next_action(kind),
            error=o.error,
        )

    if not reqs:
        trace.record(
            StepTrace(
                step="ingestion",
                status="ok",
                counts={
                    "subscription": sub.id,
                    "new_items": o.new_count,
                    "dispatched": len(o.dispatched),
                },
            )
        )
        return PollSubReport(
            subscription_id=sub.id,
            input_url=sub.input_url,
            ok=True,
            new_items=0,
            backlog_skipped=o.backlog_skipped,
        )

    sources, all_failed = _ingest_only(reqs, ingest=ingest)
    # transcription deferral is delayed processing, never a failure; the item
    # keeps its typed deferred status until the worker / detail page transcribes
    deferred = [
        r
        for r in all_failed
        if r.failure is not None and r.failure.kind == "transcription_deferred"
    ]
    failed = [r for r in all_failed if r not in deferred]

    # settle each discovered item's OWN lifecycle status (M15.1a — the row was
    # written at dispatch; nothing later deletes it)
    _settle_tracked_items(
        conn,
        o,
        sub,
        sources=sources,
        failed=failed,
        deferred=deferred,
        now=now,
    )

    # brief every fetched item NOW, while its raw text is in hand — one flash
    # call per new item, concurrent; failures write nothing (honest pending)
    summarized = _summarize_new_items(conn, o, sub, contents=sources, llm=llm)
    if summarized:
        trace.record(
            StepTrace(
                step="digest",
                status="ok",
                counts={"subscription": sub.id, "item_summaries": summarized},
            )
        )
    items_ok = len(reqs) - len(failed) - len(deferred)
    item_failures = [
        PollItemFailure(
            url=(r.failure.requested_url if r.failure else None) or r.requested.url,
            kind=r.failure.kind if r.failure else "timeout",
            next_action=r.failure.next_action if r.failure else None,
        )
        for r in failed[:MAX_ITEM_FAILURES_LISTED]
    ]
    error_summary = _item_failure_summary(failed, len(reqs)) if failed else None

    # The ingestion step is honest about per-item outcomes (M13.1): a feed whose
    # articles ALL failed to fetch is a FAILED step, not "ok with zero results".
    trace.record(
        StepTrace(
            step="ingestion",
            status="failed" if (items_ok == 0 and failed) else "ok",
            counts={
                "subscription": sub.id,
                "new_items": o.new_count,
                "dispatched": len(o.dispatched),
                "items_ok": items_ok,
                "items_failed": len(failed),
                "items_deferred": len(deferred),
            },
            error=error_summary,
        )
    )
    if items_ok == 0 and failed:
        # every processable new item failed ingestion — bubble a typed subscription
        # failure so the UI shows why + the next step, never a green "ok".
        return PollSubReport(
            subscription_id=sub.id,
            input_url=sub.input_url,
            ok=False,
            new_items=o.new_count,
            items_ok=0,
            items_failed=len(failed),
            item_failures=item_failures,
            backlog_skipped=o.backlog_skipped,
            items_deferred=len(deferred),
            failure_kind="items_unfetchable",
            next_action=subscription_next_action("items_unfetchable"),
            error=error_summary,
        )
    return PollSubReport(
        subscription_id=sub.id,
        input_url=sub.input_url,
        ok=True,
        new_items=o.new_count,
        items_ok=items_ok,
        items_failed=len(failed),
        item_failures=item_failures,
        backlog_skipped=o.backlog_skipped,
        items_deferred=len(deferred),
    )
