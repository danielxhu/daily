"""The digest API over the tracked channel (engine removed 2026-07-13):
`GET /api/digest` (rolling window, board-filterable, JSON or RSS) and
`GET /api/digest/{date}` (one UTC day). Render is cache-only, zero LLM."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.engine import init_db
from app.db.tracked_item_store import upsert_discovered
from app.main import create_app, get_db
from app.tracking.feed import FeedItem

NOW = datetime.now(UTC)


def _seed_item(
    conn: sqlite3.Connection,
    url: str,
    *,
    title: str,
    board_id: str | None = None,
    sub: str = "sub1",
    first_seen: datetime | None = None,
) -> None:
    upsert_discovered(
        conn,
        subscription_id=sub,
        board_id=board_id,
        item=FeedItem(guid=None, url=url, title=title, summary=None, published=None),
        now=first_seen or NOW,
        module_id=None,
    )
    conn.execute(
        "INSERT OR IGNORE INTO subscriptions (id, input_url, mode, interval_minutes,"
        " consecutive_failures, health) VALUES (?, ?, 'direct', 60, 0, 'ok')",
        (sub, f"https://{sub}.example/feed"),
    )
    conn.commit()


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
    return TestClient(app)


def test_digest_returns_the_tracked_channel(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    _seed_item(conn, "https://www.sec.gov/news/a", title="SEC adopts rules")
    conn.close()

    body = _client(db).get("/api/digest").json()
    assert [i["title"] for i in body["tracked"]] == ["SEC adopts rules"]
    # zero check-era vocabulary in the payload
    text = str(body)
    for banned in ("credibility", "verdict", "heat"):
        assert banned not in text.lower()


def test_board_filter(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    _seed_item(conn, "https://a.example/1", title="in board", board_id="bfin")
    _seed_item(conn, "https://b.example/2", title="elsewhere", board_id="bother", sub="sub2")
    conn.close()

    body = _client(db).get("/api/digest", params={"board_id": "bfin"}).json()
    assert [i["title"] for i in body["tracked"]] == ["in board"]


def test_view_window_bounds_and_filtering(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    _seed_item(conn, "https://a.example/old", title="old", first_seen=NOW - timedelta(days=40))
    _seed_item(conn, "https://a.example/new", title="new")
    conn.close()
    client = _client(db)

    assert [i["title"] for i in client.get("/api/digest").json()["tracked"]] == ["new"]
    both = client.get("/api/digest", params={"window_days": 90}).json()["tracked"]
    assert {i["title"] for i in both} == {"old", "new"}
    assert client.get("/api/digest", params={"window_days": 0}).status_code == 400
    assert client.get("/api/digest", params={"window_days": 9999}).status_code == 400


def test_date_endpoint_scopes_to_one_utc_day(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    day = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    _seed_item(conn, "https://a.example/that-day", title="that day", first_seen=day)
    _seed_item(
        conn, "https://a.example/other-day", title="другой", first_seen=day + timedelta(days=3)
    )
    conn.close()

    body = _client(db).get("/api/digest/2026-06-01").json()
    assert body["date"] == "2026-06-01"
    assert [i["title"] for i in body["tracked"]] == ["that day"]


def test_rss_renders_tracking_language_only(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    _seed_item(conn, "https://www.sec.gov/news/item-1", title="SEC adopts rules")
    conn.close()

    res = _client(db).get("/api/digest", params={"format": "rss"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/rss+xml")
    assert "<rss" in res.text and "SEC adopts rules" in res.text
    assert "sec.gov" in res.text and "tier T1" in res.text
    for banned in ("credibility", "verified", "verdict", "heat"):
        assert banned not in res.text.lower()


def test_empty_digest_is_valid(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    init_db(db).close()
    body = _client(db).get("/api/digest").json()
    assert body["tracked"] == []
