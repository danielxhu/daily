"""M9.10 — tracking poll runtime (SSOT §6.2–§6.6 / FR-3).

The live wire from subscription → memory/digest: `run_poll` discovers each
subscription's new items, runs them through the SAME ingestion + extraction path as
/verify, and feeds the board's rolling window via `ingest_tracked` so a corroborated
tracked fact graduates to memory. Plus the manual `POST /tracking/poll` endpoint and
the in-process hourly scheduler wired into the app lifespan.

Offline (NFR-3): `fetch` is a fake returning fixture bytes; ingestion is faked to
sec.gov (T1) sources so a single tracked item is an authoritative anchor and writes
without any cross-source NLI (members are SUPPORT by construction — no LLM stance
call); the LLM only does the (identical, order-independent) extraction."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.clients.mock import MockLLMClient
from app.core.config import Settings
from app.db.engine import init_db
from app.db.run_trace import list_runs
from app.db.subscription_store import create_subscription, get_subscription
from app.ingestion.domains import normalize_domain
from app.ingestion.result import failed_from, ok_result
from app.main import (
    create_app,
    get_db,
    get_feed_fetch,
    get_ingest,
    get_ingest_first,
    get_llm,
)
from app.schemas.models import IngestionResult, NormalizedSource, SourceRequest, Subscription
from app.tracking.runtime import PollReport, poll_due_subscriptions, run_poll
from tests.fixtures_loader import fixture_path

NOW = datetime(2026, 6, 24, tzinfo=UTC)

QUOTE = "the SEC adopted new market-structure rules"
RAW = f"In a statement, {QUOTE} that take effect next quarter."
EXTRACTION: dict[str, Any] = {
    "claims": [
        {
            "claim_text": "The SEC adopted new market-structure rules.",
            "source_quote": QUOTE,
            "type": "fact",
        }
    ]
}


def _rss() -> bytes:
    return fixture_path("feeds/rss_sample.xml").read_bytes()  # 3 sec.gov items


def _fake_ingest(req: SourceRequest) -> IngestionResult:
    """Every tracked item URL → a sec.gov (T1, primary) webpage asserting the fact."""
    domain = normalize_domain(req.url) if req.url else None
    return ok_result(
        req,
        NormalizedSource(
            source_id="s",  # run_report re-keys this; the runtime then re-keys it uniquely
            type="webpage",
            url=req.url,
            domain=domain,
            raw_text=RAW,
            segments=[],
            frame_annotations=[],
        ),
    )


def _llm() -> MockLLMClient:
    # one identical extraction per source × window — identical, so concurrent FIFO
    # order is irrelevant; plenty so the queue never exhausts (it would raise).
    return MockLLMClient([EXTRACTION] * 30)


def _sec_subscription(conn: sqlite3.Connection) -> Subscription:
    return create_subscription(
        conn,
        input_url="https://www.sec.gov/news/pressreleases",
        mode="direct",
        feed_url="https://www.sec.gov/news/pressreleases.rss",
    )


# --- run_poll: the dispatcher → window side effect -------------------------


def test_second_poll_dedups_with_no_new_side_effect(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    _sec_subscription(conn)
    common = dict(fetch=lambda _url: _rss(), ingest=_fake_ingest, now=NOW)

    def tracked_count() -> int:
        return int(conn.execute("SELECT COUNT(*) FROM tracked_items").fetchone()[0])

    run_poll(conn, llm=_llm(), **common)  # type: ignore[arg-type]
    assert tracked_count() == 3  # tracking-only poll: items stored, no facts

    again = run_poll(conn, llm=_llm(), **common)  # type: ignore[arg-type]
    assert again.new_items == 0  # seen-set dedup (M7.6)
    assert tracked_count() == 3  # no duplicate rows written


def test_one_failing_subscription_does_not_block_the_others(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    good = _sec_subscription(conn)
    bad = create_subscription(
        conn,
        input_url="https://bad.example/feed",
        mode="direct",
        feed_url="https://bad.example/feed",
    )

    def fetch(url: str) -> bytes:
        if "bad" in url:
            raise TimeoutError("down")
        return _rss()

    report = run_poll(
        conn,
        llm=_llm(),
        fetch=fetch,
        ingest=_fake_ingest,
        now=NOW,
    )
    by_id = {r.subscription_id: r for r in report.subscriptions}
    # tracking-only poll (2026-07-10): the good source's items landed; no fact writes
    assert by_id[good.id].ok and by_id[good.id].items_ok == 3  # good source unaffected …
    assert by_id[bad.id].ok is False  # … the broken one is isolated …
    assert (
        by_id[bad.id].failure_kind == "network" and by_id[bad.id].next_action
    )  # … with a next step
    # no fact writes on a tracking-only poll; the good source's items are stored
    n = conn.execute("SELECT COUNT(*) FROM tracked_items").fetchone()[0]
    assert n == 3

    # the failed subscription's health recorded the typed failure (§6.6)
    refreshed = get_subscription(conn, bad.id)
    assert refreshed is not None and refreshed.consecutive_failures == 1 and refreshed.last_error


# --- POST /tracking/poll endpoint ------------------------------------------


def _db_override(db_path: str) -> Callable[[], Iterator[sqlite3.Connection]]:
    def _get_db() -> Iterator[sqlite3.Connection]:
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    return _get_db


def test_poll_endpoint_returns_useful_counts(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    sub = _sec_subscription(conn)
    conn.close()

    app = create_app()
    app.dependency_overrides[get_db] = _db_override(db)
    app.dependency_overrides[get_llm] = _llm
    app.dependency_overrides[get_ingest] = lambda: _fake_ingest
    # M14.5: the first-poll ingest is its own dependency; these webpage items need
    # no transcription, so the same fake stands in for both
    app.dependency_overrides[get_ingest_first] = lambda: _fake_ingest
    app.dependency_overrides[get_feed_fetch] = lambda: lambda _url: _rss()

    res = TestClient(app).post("/tracking/poll")
    assert res.status_code == 200
    body = res.json()
    assert body["polled"] == 1 and body["new_items"] == 3
    assert body["run_id"] and body["system_anomaly"] is False
    assert body["subscriptions"][0]["subscription_id"] == sub.id and body["subscriptions"][0]["ok"]


# --- in-process hourly scheduler wired into the app lifespan ---------------


class _FakeBackend:
    """Stands in for APScheduler (not in the offline venv): records jobs, no clock."""

    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self.started = False
        self.stopped = False

    def add_job(self, func: Any, trigger: str, **kwargs: Any) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def start(self) -> None:
        self.started = True

    def shutdown(self) -> None:
        self.stopped = True


def test_lifespan_runs_one_tick_that_polls_subscriptions_added_after_startup(
    tmp_path: Path,
) -> None:
    db = str(tmp_path / "daily.db")
    init_db(db).close()  # start with NO subscriptions

    def tick() -> None:
        # the real tick re-reads the DB each run; here with offline fakes
        conn = init_db(db)
        try:
            poll_due_subscriptions(
                conn,
                llm=_llm(),
                fetch=lambda _url: _rss(),
                ingest=_fake_ingest,
            )
        finally:
            conn.close()

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, sqlite_path=db, enable_tracking_scheduler=True, poll_tick_minutes=5
    )
    app = create_app(settings)
    backend = _FakeBackend()
    app.state.scheduler_backend = backend
    app.state.poll_runner = tick

    with TestClient(app):  # entering the context runs the lifespan startup
        # ONE recurring poll tick (not one job per subscription) + the background
        # enrichment tick (2026-07-10) — never a job per source
        assert [j["id"] for j in backend.jobs] == ["poll:tick", "enrich:tick"]
        assert backend.jobs[0]["trigger"] == "interval" and backend.jobs[0]["minutes"] == 5
        assert backend.jobs[1]["trigger"] == "interval" and backend.jobs[1]["seconds"] == 30
        assert backend.started
        # a source ADDED AFTER startup …
        conn = init_db(db)
        _sec_subscription(conn)
        conn.close()
        # … is picked up on the next tick (it re-reads the DB) → proves dynamic
        # membership. The tracking-only poll writes items, not facts (2026-07-10).
        backend.jobs[0]["func"]()
        n = init_db(db).execute("SELECT COUNT(*) FROM tracked_items").fetchone()[0]
        assert n == 3

    assert backend.stopped  # lifespan shutdown stops the scheduler


def test_scheduler_off_by_default_starts_no_jobs(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    init_db(db).close()
    app = create_app(Settings(_env_file=None, sqlite_path=db))  # type: ignore[call-arg]
    backend = _FakeBackend()
    app.state.scheduler_backend = backend
    with TestClient(app):
        pass
    assert backend.jobs == [] and not backend.started  # opt-in only (enable_tracking_scheduler)


def test_poll_due_only_polls_subscriptions_past_their_interval(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    _sec_subscription(conn)  # interval 60 min, never polled

    def due(now: datetime) -> PollReport | None:
        return poll_due_subscriptions(
            conn,
            llm=_llm(),
            fetch=lambda _url: _rss(),
            ingest=_fake_ingest,
            now=now,
        )

    t0 = datetime.now(UTC)
    first = due(t0)
    assert first is not None and first.polled == 1  # never polled → due
    # last_polled is set on a clean poll; not due again until its interval elapses
    assert due(t0 + timedelta(minutes=30)) is None
    later = due(t0 + timedelta(minutes=61))
    assert later is not None and later.polled == 1  # interval elapsed → due again


# --- M13.1 (beta P0-1): per-item failures bubble up, never silence --------------


def _anti_bot_ingest(req: SourceRequest) -> IngestionResult:
    """Every article page is bot-blocked — the federalreserve.gov case: the FEED
    polls fine, the items themselves can't be fetched."""
    return failed_from(
        req, "anti_bot", reason="blocked by anti-bot challenge", requested_url=req.url
    )


def test_all_items_failing_is_a_typed_failure_not_silence(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    sub = _sec_subscription(conn)
    common = dict(llm=_llm(), now=NOW)

    report = run_poll(
        conn,
        fetch=lambda _url: _rss(),
        ingest=_anti_bot_ingest,
        **common,  # type: ignore[arg-type]
    )

    # the report is honest: found items, ok=False, typed kind + counts + next step
    s = report.subscriptions[0]
    assert s.ok is False and s.failure_kind == "items_unfetchable"
    assert s.new_items == 3 and s.items_ok == 0 and s.items_failed == 3
    assert [f.kind for f in s.item_failures] == ["anti_bot"] * 3
    assert s.item_failures[0].url is not None and s.item_failures[0].next_action
    assert s.error is not None and "3/3 new items failed" in s.error
    assert s.next_action is not None and "Paste the article text" in s.next_action

    # the failure reaches the subscription ROW immediately (kind + error visible in
    # the UI even before the unhealthy threshold) and is NOT reset by the feed-level
    # success path (the feed itself fetched fine)
    refreshed = get_subscription(conn, sub.id)
    assert refreshed is not None
    assert refreshed.subscription_failure_kind == "items_unfetchable"
    assert refreshed.last_error is not None and "anti_bot" in refreshed.last_error
    assert refreshed.consecutive_failures == 1

    # the run trace records a FAILED ingestion step with per-item counts (§6.6),
    # so the operator has a real debugging trail — not an all-green dead end
    runs = list_runs(conn)
    ingestion = next(t for t in runs[0].steps if t.step == "ingestion")
    assert ingestion.status == "failed"
    assert ingestion.counts["items_ok"] == 0 and ingestion.counts["items_failed"] == 3
    assert ingestion.error is not None and "anti_bot" in ingestion.error

    # a later clean poll resets the bookkeeping (§6.6) — new content, all fetchable
    conn.execute("DELETE FROM seen_items")  # forget dedup so the same items re-poll
    conn.commit()
    run_poll(conn, fetch=lambda _url: _rss(), ingest=_fake_ingest, **common)  # type: ignore[arg-type]
    reset = get_subscription(conn, sub.id)
    assert reset is not None
    assert reset.consecutive_failures == 0 and reset.subscription_failure_kind is None


def test_concurrent_poll_is_refused_honestly_not_a_zero_report(tmp_path: Path) -> None:
    """M14.4: a second poll while one runs used to see every item already marked
    seen and report a misleading 'checked N · 0 new'. Now it is refused (409 at
    the endpoint; the scheduler tick just skips)."""
    from app.tracking import runtime as rt

    conn = init_db(str(tmp_path / "daily.db"))
    _sec_subscription(conn)
    common = dict(llm=_llm(), now=NOW)

    assert rt._POLL_MUTEX.acquire(blocking=False)  # simulate a poll in flight
    try:
        # direct runtime call raises the typed error …
        import pytest

        with pytest.raises(rt.PollInProgressError):
            run_poll(conn, fetch=lambda _url: _rss(), ingest=_fake_ingest, **common)  # type: ignore[arg-type]
        # … the scheduler tick skips silently instead of stacking a second poll
        assert (
            poll_due_subscriptions(conn, fetch=lambda _url: _rss(), ingest=_fake_ingest, **common)  # type: ignore[arg-type]
            is None
        )
    finally:
        rt._POLL_MUTEX.release()

    # once free, the poll runs normally again
    report = run_poll(conn, fetch=lambda _url: _rss(), ingest=_fake_ingest, **common)  # type: ignore[arg-type]
    assert report.polled == 1


def test_poll_endpoint_answers_409_while_a_check_runs(tmp_path: Path) -> None:
    from app.tracking import runtime as rt

    db = str(tmp_path / "daily.db")
    init_db(db).close()
    app = create_app()
    app.dependency_overrides[get_db] = _db_override(db)
    app.dependency_overrides[get_llm] = lambda: _llm()
    app.dependency_overrides[get_feed_fetch] = lambda: lambda _url: _rss()
    app.dependency_overrides[get_ingest] = lambda: _fake_ingest
    client = TestClient(app)

    assert rt._POLL_MUTEX.acquire(blocking=False)
    try:
        res = client.post("/tracking/poll")
        assert res.status_code == 409
        assert "already running" in res.json()["detail"]
    finally:
        rt._POLL_MUTEX.release()


# --- M14.7: the poll (not the page open) fills the digest caches ------------


class _KeyedLLM:
    """Content-keyed fake (MockLLMClient is FIFO — concurrent phases would race):
    answers the summary/category prompts by system-prompt content, extraction
    otherwise. Records nothing; the assertions read the caches."""

    def complete_json(self, *, system: str, user: str, escalate: bool = False) -> dict[str, Any]:
        if "summary_zh" in system:  # M16.3 bilingual item enrichment
            return {
                "summary_zh": "来源称规则进入评议期。",
                "summary_en": "The source says the rules enter a comment period.",
                "title_zh": "来源标题(中文)",
                "title_en": "Source title (English)",
                "why_zh": "与市场结构规则相关。",
                "why_en": "Relevant to market-structure rules.",
                "entities": ["SEC"],
                "tags": ["policy"],
                "limitations_zh": "仅基于正文节选。",
                "limitations_en": "Based on an excerpt only.",
            }
        if "briefing summary" in system:  # digest fact summary (M12.2)
            return {"summary": "A briefing line."}
        if "Classify a financial news item" in system:
            return {"category": "policy"}
        return EXTRACTION


def _deferring_ingest(req: SourceRequest) -> IngestionResult:
    """Fake first-check ingest: every item would need whisper → typed deferral."""
    return failed_from(
        req,
        "transcription_deferred",
        reason="first check defers transcription; the next check processes this item",
        requested_url=req.url,
        source_type="podcast",
    )


def test_polls_always_defer_transcription_without_requeue_churn(tmp_path: Path) -> None:
    """M14.5 → 2026-07-10 (owner "轮询好慢"): EVERY poll uses the fast ingest —
    whisper never runs inside a poll (one video costs minutes; a backlog queued
    them serially for hours). Deferral is honest delayed processing, and the item
    is NOT re-queued: the next poll must not re-fetch it forever — the detail
    page's fetch-&-summarize is the on-demand transcription path."""
    conn = init_db(str(tmp_path / "daily.db"))
    _sec_subscription(conn)

    def check(now: datetime) -> PollReport:
        return run_poll(
            conn,
            llm=_KeyedLLM(),
            fetch=lambda _url: _rss(),
            ingest=_fake_ingest,
            ingest_first=_deferring_ingest,
            now=now,
        )

    first = check(NOW)
    r1 = first.subscriptions[0]
    # deferral is honest delayed processing: an ok report, no failure kind, nothing
    # counted as failed, and no fact written
    assert r1.ok and r1.failure_kind is None
    assert r1.items_deferred == 3 and r1.items_failed == 0 and r1.items_ok == 0

    second = check(NOW + timedelta(hours=1))
    r2 = second.subscriptions[0]
    # NOT re-discovered — the items stay seen (no per-poll re-fetch churn) and
    # keep their honest deferred status until the user transcribes on demand
    assert r2.new_items == 0 and r2.items_deferred == 0
    statuses = [
        row["status"] for row in conn.execute("SELECT status FROM tracked_items").fetchall()
    ]
    assert statuses and all(s == "deferred" for s in statuses)


def test_first_poll_mixed_deferral_still_reports_failures_honestly(tmp_path: Path) -> None:
    """Deferred items never dilute real failures: with every processable item
    blocked, the subscription still bubbles items_unfetchable (M13.1)."""
    conn = init_db(str(tmp_path / "daily.db"))
    _sec_subscription(conn)
    calls = {"n": 0}

    def half_deferring(req: SourceRequest) -> IngestionResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return _deferring_ingest(req)
        return failed_from(req, "anti_bot", reason="blocked", requested_url=req.url)

    report = run_poll(
        conn,
        llm=_KeyedLLM(),
        fetch=lambda _url: _rss(),
        ingest=_fake_ingest,
        ingest_first=half_deferring,
        now=NOW,
    )
    r = report.subscriptions[0]
    assert r.items_deferred == 1 and r.items_failed == 2
    assert r.failure_kind == "items_unfetchable"  # the real failures still bubble
    assert all(f.kind != "transcription_deferred" for f in r.item_failures)
