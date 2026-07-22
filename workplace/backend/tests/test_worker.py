"""The background enrichment worker (owner 2026-07-10): pending items upgrade
themselves — summary-only first, then fetches, then ONE transcription per tick;
attempts are bounded per app run; a running poll makes the tick skip cleanly."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.db.engine import init_db
from app.db.tracked_item_store import upsert_discovered
from app.ingestion.result import failed_from
from app.schemas.models import IngestionResult, SourceRequest
from app.tracking import worker
from app.tracking.feed import FeedItem
from app.tracking.runtime import _POLL_MUTEX
from app.tracking.worker import work_once
from tests.test_tracking_runtime import _fake_ingest, _KeyedLLM

NOW = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


def _reset_worker_state() -> None:
    worker._fetch_attempts.clear()
    worker._fetch_next_try.clear()
    worker._summary_failures.clear()


def _seed(
    conn: sqlite3.Connection,
    url: str,
    *,
    sub: str = "sub1",
    excerpt: str | None = None,
    status: str | None = None,
) -> str:
    # a REAL subscription row anchors the item — the tick's orphan purge
    # (2026-07-13) removes items whose subscription is gone, ghost ids included
    if sub != "sub_ghost":
        conn.execute(
            "INSERT OR IGNORE INTO subscriptions (id, input_url, mode, interval_minutes,"
            " consecutive_failures, health) VALUES (?, ?, 'direct', 60, 0, 'ok')",
            (sub, f"https://{sub}.example/feed"),
        )
    upsert_discovered(
        conn,
        subscription_id=sub,
        board_id="b1",
        item=FeedItem(guid=None, url=url, title=url, summary=None, published=None),
        now=NOW,
        module_id=None,
    )
    row = conn.execute("SELECT id FROM tracked_items WHERE url = ?", (url,)).fetchone()
    if excerpt is not None:
        conn.execute(
            "UPDATE tracked_items SET content_excerpt = ? WHERE id = ?", (excerpt, row["id"])
        )
    if status is not None:
        conn.execute("UPDATE tracked_items SET status = ? WHERE id = ?", (status, row["id"]))
    conn.commit()
    return str(row["id"])


def test_worker_processes_all_three_classes_in_priority_order(tmp_path: Path) -> None:
    _reset_worker_state()
    conn = init_db(str(tmp_path / "daily.db"))
    with_text = _seed(conn, "https://a.example/1", excerpt="stored body", status="fetched")
    no_text = _seed(conn, "https://www.sec.gov/news/item-1", sub="sub2")
    deferred = _seed(conn, "https://pod.example/ep", sub="sub3", status="deferred")

    transcribed: list[str] = []

    def transcribe(req: SourceRequest) -> IngestionResult:
        transcribed.append(req.url or "")
        return _fake_ingest(req)

    counts = work_once(conn, llm=_KeyedLLM(), ingest=_fake_ingest, transcribe_ingest=transcribe)
    assert counts == {"summarized": 1, "fetched": 1, "transcribed": 1, "indexed": 0}
    enriched = {
        r["id"]
        for r in conn.execute(
            "SELECT id FROM tracked_items WHERE enrichment IS NOT NULL"
        ).fetchall()
    }
    assert {with_text, no_text, deferred} <= enriched
    assert transcribed == ["https://pod.example/ep"]  # only the deferred item


def test_worker_retries_a_failing_site_with_a_cooldown_not_every_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 2026-07-19: temporary failures lift on their own — a bounded retry budget
    # with an escalating cooldown replaces one-attempt-per-process, and ticks
    # inside the cooldown never touch the site. (A non-risk-control failure:
    # risk control now freezes the whole DOMAIN — tested separately below.)
    _reset_worker_state()
    conn = init_db(str(tmp_path / "daily.db"))
    _seed(conn, "https://flaky.example/a")

    calls = {"n": 0}

    def flaky(req: SourceRequest) -> IngestionResult:
        calls["n"] += 1
        return failed_from(req, "parse_empty", reason="no main text", requested_url=req.url)

    for _ in range(3):  # three ticks inside the cooldown window → one attempt
        work_once(conn, llm=_KeyedLLM(), ingest=flaky, transcribe_ingest=flaky)
    assert calls["n"] == 1
    # cooldown elapsed (simulated: drop the scheduled next-try timestamps) →
    # the next ticks retry, up to the bounded budget
    monkeypatch.setattr(worker, "_RETRY_COOLDOWNS", (0.0,))
    worker._fetch_next_try.clear()
    for _ in range(10):
        work_once(conn, llm=_KeyedLLM(), ingest=flaky, transcribe_ingest=flaky)
    assert calls["n"] == worker._FETCH_MAX_TRIES  # budget spent, then it rests
    # a manual refresh resets the budget — the user explicitly asked
    row = conn.execute("SELECT id FROM tracked_items").fetchone()
    worker.reset_attempts(str(row["id"]))
    work_once(conn, llm=_KeyedLLM(), ingest=flaky, transcribe_ingest=flaky)
    assert calls["n"] == worker._FETCH_MAX_TRIES + 1


def test_risk_control_failure_freezes_the_whole_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 2026-07-21 audit: bilibili 412 is domain-wide and hour-scale. ONE such
    # failure must stop every background request to that domain — including
    # OTHER items — while an unrelated domain keeps processing.
    _reset_worker_state()
    conn = init_db(str(tmp_path / "daily.db"))
    _seed(conn, "https://hostile.example/video1")
    _seed(conn, "https://hostile.example/video2", sub="sub2")
    ok_item = _seed(conn, "https://calm.example/post", sub="sub3")

    calls: dict[str, int] = {}

    def ingest(req: SourceRequest) -> IngestionResult:
        calls[req.url or "?"] = calls.get(req.url or "?", 0) + 1
        if "hostile.example" in (req.url or ""):
            return failed_from(
                req,
                "fetch_blocked",
                reason="Request is blocked by server (412), please wait",
                requested_url=req.url,
            )
        return _fake_ingest(req)

    monkeypatch.setattr(worker, "_RETRY_COOLDOWNS", (0.0,))
    for _ in range(6):
        work_once(conn, llm=_KeyedLLM(), ingest=ingest, transcribe_ingest=ingest)

    # exactly ONE knock on the frozen domain — the second item never even tried
    assert sum(n for url, n in calls.items() if "hostile.example" in url) == 1
    assert (
        conn.execute(
            "SELECT consecutive FROM domain_backoff WHERE domain = 'hostile.example'"
        ).fetchone()
        is not None
    )
    # the unrelated domain was unaffected
    enriched = conn.execute(
        "SELECT enrichment FROM tracked_items WHERE id = ?", (ok_item,)
    ).fetchone()
    assert enriched["enrichment"] is not None


def test_worker_skips_cleanly_while_a_poll_is_running(tmp_path: Path) -> None:
    _reset_worker_state()
    conn = init_db(str(tmp_path / "daily.db"))
    _seed(conn, "https://a.example/1", excerpt="stored body", status="fetched")

    assert _POLL_MUTEX.acquire(blocking=False)
    try:
        counts = work_once(
            conn, llm=_KeyedLLM(), ingest=_fake_ingest, transcribe_ingest=_fake_ingest
        )
    finally:
        _POLL_MUTEX.release()
    assert counts == {"summarized": 0, "fetched": 0, "transcribed": 0, "indexed": 0}
    # nothing consumed the attempt budget — the next tick picks the items up
    counts = work_once(conn, llm=_KeyedLLM(), ingest=_fake_ingest, transcribe_ingest=_fake_ingest)
    assert counts["summarized"] == 1


def test_summary_failures_get_two_tries_then_rest(tmp_path: Path) -> None:
    _reset_worker_state()

    class _Boom:
        calls = 0

        def complete_json(self, **_: object) -> dict[str, object]:
            type(self).calls += 1
            raise RuntimeError("llm down")

    conn = init_db(str(tmp_path / "daily.db"))
    _seed(conn, "https://a.example/1", excerpt="stored body", status="fetched")
    for _ in range(4):
        work_once(conn, llm=_Boom(), ingest=_fake_ingest, transcribe_ingest=_fake_ingest)
    assert _Boom.calls == 2  # bounded — an outage never burns retries forever


def test_worker_tick_purges_orphaned_items(tmp_path: Path) -> None:
    """The 30-second tick heals deleted-source leftovers too (owner 2026-07-13)."""
    from app.db.tracked_item_store import recent_tracked_items

    _reset_worker_state()
    conn = init_db(str(tmp_path / "daily.db"))
    _seed(conn, "https://ghost.example/a", sub="sub_ghost")
    conn.execute("DELETE FROM subscriptions WHERE 1=1")  # no-op: none were created
    work_once(conn, llm=_KeyedLLM(), ingest=_fake_ingest, transcribe_ingest=_fake_ingest)
    assert recent_tracked_items(conn, since=NOW.replace(year=2025)) == []
