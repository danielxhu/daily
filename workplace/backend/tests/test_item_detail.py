"""M16.4 — the tracked-item detail payload + the manual fetch-&-summarize refresh.

Detail = card + "Source says" excerpt preview (the provenance/related blocks left
the page 2026-07-13). Refresh = ingestion + excerpt + bilingual enrichment ONLY —
deliberately NOT a deep check. Failures are typed and loud: the user clicked."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.engine import init_db
from app.db.tracked_item_store import (
    recent_tracked_items,
    upsert_discovered,
)
from app.ingestion.result import failed_from
from app.main import create_app, get_db, get_ingest, get_ingest_first, get_llm
from app.schemas.models import IngestionResult, SourceRequest
from app.tracking.feed import FeedItem
from app.tracking.refresh import RefreshFailedError, refresh_item
from app.tracking.runtime import _POLL_MUTEX
from tests.test_tracking_runtime import _fake_ingest, _KeyedLLM

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _discover(
    conn: sqlite3.Connection,
    url: str,
    *,
    title: str | None = "An item",
    sub_id: str = "sub1",
    board_id: str | None = "b_economy",
    module_id: str | None = None,
) -> str:
    upsert_discovered(
        conn,
        subscription_id=sub_id,
        board_id=board_id,
        item=FeedItem(guid=None, url=url, title=title, summary=None, published=None),
        now=NOW,
        module_id=module_id,
    )
    conn.commit()
    row = conn.execute("SELECT id FROM tracked_items WHERE url = ?", (url,)).fetchone()
    return str(row["id"])


def _boom_ingest(req: SourceRequest) -> IngestionResult:
    return failed_from(req, "anti_bot", reason="blocked")


def _db_override(db_path: str) -> Callable[[], Iterator[sqlite3.Connection]]:
    def _get_db() -> Iterator[sqlite3.Connection]:
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    return _get_db


def _client(db_path: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = _db_override(db_path)
    app.dependency_overrides[get_llm] = lambda: _KeyedLLM()
    app.dependency_overrides[get_ingest] = lambda: _fake_ingest
    # the refresh endpoint uses the whisper-free ingest (2026-07-19)
    app.dependency_overrides[get_ingest_first] = lambda: _fake_ingest
    return TestClient(app)


# --- refresh (fetch & summarize, NOT a deep check) ---------------------------


def test_refresh_fills_excerpt_enrichment_and_method_without_verification(
    tmp_path: Path,
) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    item_id = _discover(conn, "https://www.sec.gov/news/item-1", title="SEC adopts rules")

    card = refresh_item(conn, item_id, llm=_KeyedLLM(), ingest=_fake_ingest, now=NOW)
    assert card.status == "fetched"
    assert card.content_available is True
    assert card.enrichment is not None
    assert card.enrichment.summary_zh == "来源称规则进入评议期。"
    # NOT a deep check: nothing entered the dormant verification layer
    assert conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0] == 0


def test_refresh_blocked_fetch_falls_back_to_the_stored_text(tmp_path: Path) -> None:
    # owner 2026-07-10: a poll stored the text but the summary never generated
    # (LLM outage); the site now blocks re-fetching (e.g. 36kr anti-bot). The
    # stored text is still good grounding — summarize from it instead of failing.
    conn = init_db(str(tmp_path / "daily.db"))
    item_id = _discover(conn, "https://www.sec.gov/news/item-1", title="SEC adopts rules")
    conn.execute(
        "UPDATE tracked_items SET content_excerpt = ?, status = 'fetched' WHERE id = ?",
        ("The stored body from the earlier poll.", item_id),
    )
    conn.commit()

    card = refresh_item(conn, item_id, llm=_KeyedLLM(), ingest=_boom_ingest, now=NOW)
    assert card.enrichment is not None
    assert card.enrichment.summary_zh == "来源称规则进入评议期。"
    # the stored excerpt is untouched — no fetch happened
    row = conn.execute(
        "SELECT content_excerpt FROM tracked_items WHERE id = ?", (item_id,)
    ).fetchone()
    assert row["content_excerpt"] == "The stored body from the earlier poll."


def test_refresh_fetch_failure_leaves_the_row_untouched(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    item_id = _discover(conn, "https://www.sec.gov/news/item-1")
    try:
        refresh_item(conn, item_id, llm=_KeyedLLM(), ingest=_boom_ingest, now=NOW)
        raise AssertionError("expected RefreshFailedError")
    except RefreshFailedError as exc:
        assert "anti_bot" in str(exc)
    # a failed RETRY downgraded nothing: still the freshly-discovered state
    cards = recent_tracked_items(conn, since=NOW.replace(year=NOW.year - 1))
    assert cards[0].status == "new" and cards[0].content_available is False


def test_refresh_never_transcribes_synchronously_it_defers_to_the_worker(
    tmp_path: Path,
) -> None:
    # owner 2026-07-19 ("这他妈抓了快十分钟了"): a caption-less video used to
    # download throttled audio + run whisper INSIDE the request. Now the refresh
    # returns immediately with the item queued (deferred) for the background
    # worker — no error, no LLM call.
    def _defer_ingest(req: SourceRequest) -> IngestionResult:
        return failed_from(req, "transcription_deferred", reason="no captions; audio needs whisper")

    conn = init_db(str(tmp_path / "daily.db"))
    item_id = _discover(conn, "https://www.bilibili.com/video/BV1demo", title="A video")
    quiet = _KeyedLLM()
    card = refresh_item(conn, item_id, llm=quiet, ingest=_defer_ingest, now=NOW)
    assert card.status == "deferred"
    assert card.failure_kind == "transcription_deferred"
    assert card.content_available is False and card.enrichment is None
    # …and the worker's transcribe query now matches this row
    row = conn.execute(
        "SELECT COUNT(*) FROM tracked_items WHERE status = 'deferred'"
        " AND enrichment IS NULL AND url IS NOT NULL"
    ).fetchone()
    assert row[0] == 1


def test_refresh_enrichment_failure_keeps_the_excerpt(tmp_path: Path) -> None:
    class _Boom:
        def complete_json(self, **_: object) -> dict[str, object]:
            raise RuntimeError("llm down")

    conn = init_db(str(tmp_path / "daily.db"))
    item_id = _discover(conn, "https://www.sec.gov/news/item-1")
    try:
        refresh_item(conn, item_id, llm=_Boom(), ingest=_fake_ingest, now=NOW)
        raise AssertionError("expected RefreshFailedError")
    except RefreshFailedError as exc:
        assert "summary generation" in str(exc)
    cards = recent_tracked_items(conn, since=NOW.replace(year=NOW.year - 1))
    # the fetch DID land: excerpt + status settle honestly; only the briefing is missing
    assert cards[0].status == "fetched"
    assert cards[0].content_available is True and cards[0].enrichment is None


def test_refresh_endpoint_maps_errors_and_honors_the_poll_mutex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # writes wait for the lock (2026-07-13) — shrink the wait so the busy path
    # answers 409 in milliseconds instead of the real 30s grace
    monkeypatch.setattr("app.tracking.refresh._LOCK_TIMEOUT_SECONDS", 0.05)
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    item_id = _discover(conn, "https://www.sec.gov/news/item-1")
    keyless = _discover(conn, "https://x.example/keyless")
    conn.execute("UPDATE tracked_items SET url = NULL WHERE id = ?", (keyless,))
    conn.commit()
    conn.close()
    client = _client(db)

    assert client.post("/tracked-items/nope/refresh").status_code == 404
    assert client.post(f"/tracked-items/{keyless}/refresh").status_code == 400
    assert _POLL_MUTEX.acquire(blocking=False)
    try:
        assert client.post(f"/tracked-items/{item_id}/refresh").status_code == 409
    finally:
        _POLL_MUTEX.release()

    res = client.post(f"/tracked-items/{item_id}/refresh")
    assert res.status_code == 200
    body = res.json()
    assert body["item"]["enrichment"]["summary_en"].startswith("The source says")
    assert body["excerpt_preview"]  # Source says material is in the payload
    assert body["item"]["content_available"] is True


# --- detail payload -----------------------------------------------------------


def test_detail_returns_the_card_and_excerpt_preview_only(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    item_id = _discover(conn, "https://www.sec.gov/news/item-1", title="SEC adopts rules")
    refresh_item(conn, item_id, llm=_KeyedLLM(), ingest=_fake_ingest, now=NOW)
    conn.close()

    res = _client(db).get(f"/tracked-items/{item_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["item"]["id"] == item_id
    assert body["excerpt_preview"]
    assert len(body["excerpt_preview"]) <= 2000
    # the provenance/related blocks left the payload with the page (2026-07-13)
    assert set(body) == {"item", "excerpt_preview"}
    # zero check language anywhere in the payload keys/values
    assert "credibility" not in res.text and "verdict" not in res.text

    assert _client(db).get("/tracked-items/nope").status_code == 404
