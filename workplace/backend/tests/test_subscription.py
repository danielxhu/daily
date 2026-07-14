"""M7.1 — Subscription CRUD (SSOT FR-3 / §7).

A subscription is a pollable source attached to a board; M7.1 is plain CRUD. The
scope red line holds: tracking polls operator-given sources, never topic-wide web
discovery, and the schema has no user/account/auth tables. A fresh subscription is
unpolled + healthy; the poll machinery (M7.6+) fills the runtime fields later."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.board_store import create_board, delete_board
from app.db.engine import init_db
from app.db.subscription_store import (
    create_subscription,
    delete_subscription,
    get_subscription,
    list_subscriptions,
)
from app.main import create_app, get_db


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


# --- store -----------------------------------------------------------------


def test_create_get_delete_roundtrip(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    board = create_board(conn, "finance")
    sub = create_subscription(
        conn,
        input_url="https://www.federalreserve.gov/feeds/press_all.xml",
        mode="direct",
        board_id=board.id,
        feed_url="https://www.federalreserve.gov/feeds/press_all.xml",
    )
    assert sub.id
    # fresh subscription: never polled, healthy, no failures (poll loop fills these)
    assert sub.last_polled is None
    assert sub.last_seen_item_key_for_display is None
    assert sub.health == "ok"
    assert sub.consecutive_failures == 0
    assert sub.subscription_failure_kind is None
    assert sub.interval_minutes == 60

    fetched = get_subscription(conn, sub.id)
    assert fetched is not None and fetched.input_url == sub.input_url
    assert fetched.board_id == board.id and fetched.mode == "direct"

    assert delete_subscription(conn, sub.id) is True
    assert get_subscription(conn, sub.id) is None


def test_delete_missing_is_false(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    assert delete_subscription(conn, "nope") is False


def test_list_filters_by_board(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    a = create_board(conn, "finance")
    b = create_board(conn, "tech")
    create_subscription(conn, input_url="https://a.example/feed", mode="direct", board_id=a.id)
    create_subscription(conn, input_url="https://b.example/feed", mode="direct", board_id=b.id)
    # a standalone (board-less) tracked source
    create_subscription(conn, input_url="https://global.example/feed", mode="direct")

    assert {s.input_url for s in list_subscriptions(conn, board_id=a.id)} == {
        "https://a.example/feed"
    }
    assert len(list_subscriptions(conn)) == 3  # all, including the board-less one


def test_homepage_diff_subscription_has_no_feed(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(conn, input_url="https://investor.nvidia.com/", mode="homepage_diff")
    assert sub.feed_url is None and sub.board_id is None


def test_deleting_a_board_removes_its_subscriptions(tmp_path: Path) -> None:
    # board-scoped subscriptions are removed with the board (app-layer cleanup in
    # delete_board, NOT a cross-domain DB FK); the shared fact store is untouched.
    conn = init_db(str(tmp_path / "daily.db"))
    board = create_board(conn, "finance")
    sub = create_subscription(
        conn, input_url="https://a.example/feed", mode="direct", board_id=board.id
    )
    assert delete_board(conn, board.id) is True
    assert get_subscription(conn, sub.id) is None


def test_tracking_domain_alone_supports_board_less_crud(tmp_path: Path) -> None:
    # X0.6 domain-independent migration: the tracking domain must migrate AND work on
    # its own. A board-less subscription has no cross-domain FK to resolve, so CRUD
    # succeeds without the board domain present.
    conn = init_db(str(tmp_path / "daily.db"), domains=["tracking"])
    sub = create_subscription(conn, input_url="https://a.example/feed", mode="direct")
    assert sub.board_id is None
    assert [s.id for s in list_subscriptions(conn)] == [sub.id]
    assert delete_subscription(conn, sub.id) is True


def test_delete_board_on_board_only_db_without_tracking_table(tmp_path: Path) -> None:
    # the board domain can migrate alone: delete_board's subscription cleanup must
    # not assume the tracking table exists (the defensive table-existence guard).
    conn = init_db(str(tmp_path / "daily.db"), domains=["board"])
    board = create_board(conn, "finance")
    assert delete_board(conn, board.id) is True


# --- API -------------------------------------------------------------------


def test_api_create_list_delete(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "daily.db"))
    board = client.post("/boards", json={"name": "finance"}).json()

    created = client.post(
        "/subscriptions",
        json={
            "input_url": "https://www.sec.gov/news/pressreleases.rss",
            "mode": "direct",
            "board_id": board["id"],
            "feed_url": "https://www.sec.gov/news/pressreleases.rss",
        },
    )
    assert created.status_code == 201
    sub = created.json()
    assert sub["health"] == "ok" and sub["board_id"] == board["id"]

    listed = client.get("/subscriptions", params={"board_id": board["id"]}).json()
    assert [s["id"] for s in listed] == [sub["id"]]

    assert client.delete(f"/subscriptions/{sub['id']}").status_code == 204
    assert client.get("/subscriptions").json() == []


def test_api_create_on_unknown_board_404(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "daily.db"))
    res = client.post(
        "/subscriptions",
        json={"input_url": "https://a.example/feed", "mode": "direct", "board_id": "ghost"},
    )
    assert res.status_code == 404


def test_api_empty_url_400_and_bad_mode_422(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "daily.db"))
    assert (
        client.post("/subscriptions", json={"input_url": "  ", "mode": "direct"}).status_code == 400
    )
    # mode is a §7 Literal — an unknown mode is rejected by validation
    assert (
        client.post(
            "/subscriptions", json={"input_url": "https://a.example", "mode": "magic"}
        ).status_code
        == 422
    )


def test_api_delete_missing_404(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "daily.db"))
    assert client.delete("/subscriptions/nope").status_code == 404


def test_deleting_a_subscription_removes_its_items_from_today(tmp_path: Path) -> None:
    """Owner 2026-07-10: "在来源里面把一个 source 删掉了,在今日里面还能看到他的消息"
    — removing a source takes its discovered items (and seen-set/lineage) with it;
    another source's items are untouched."""
    from datetime import UTC, datetime

    from app.db.tracked_item_store import recent_tracked_items, upsert_discovered
    from app.tracking.feed import FeedItem

    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    conn = init_db(str(tmp_path / "daily.db"))
    keep = create_subscription(conn, input_url="https://keep.example/feed", mode="direct")
    gone = create_subscription(conn, input_url="https://gone.example/feed", mode="direct")
    for sub, url in ((keep, "https://keep.example/a"), (gone, "https://gone.example/b")):
        upsert_discovered(
            conn,
            subscription_id=sub.id,
            board_id=None,
            item=FeedItem(guid=None, url=url, title=url, summary=None, published=None),
            now=now,
            module_id=None,
        )
    conn.commit()

    assert delete_subscription(conn, gone.id) is True
    urls = [c.url for c in recent_tracked_items(conn, since=now.replace(year=2025))]
    assert urls == ["https://keep.example/a"]  # the removed source's item is gone
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM seen_items WHERE subscription_id = ?", (gone.id,)
        ).fetchone()[0]
        == 0
    )


def test_deleting_a_board_removes_its_sources_items(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from app.db.tracked_item_store import recent_tracked_items, upsert_discovered
    from app.tracking.feed import FeedItem

    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    conn = init_db(str(tmp_path / "daily.db"))
    board = create_board(conn, "Finance")
    sub = create_subscription(
        conn, input_url="https://b.example/feed", mode="direct", board_id=board.id
    )
    upsert_discovered(
        conn,
        subscription_id=sub.id,
        board_id=board.id,
        item=FeedItem(
            guid=None, url="https://b.example/x", title="x", summary=None, published=None
        ),
        now=now,
        module_id=None,
    )
    conn.commit()

    assert delete_board(conn, board.id) is True
    assert recent_tracked_items(conn, since=now.replace(year=2025)) == []


def test_orphaned_items_are_purged(tmp_path: Path) -> None:
    """Items left behind by deletions made BEFORE the cascade existed (owner
    2026-07-10 follow-up: they kept showing in Today) are swept by the poll-start
    purge; a live subscription's items are untouched."""
    from datetime import UTC, datetime

    from app.db.subscription_store import purge_orphaned_items
    from app.db.tracked_item_store import recent_tracked_items, upsert_discovered
    from app.tracking.feed import FeedItem

    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    conn = init_db(str(tmp_path / "daily.db"))
    live = create_subscription(conn, input_url="https://live.example/feed", mode="direct")
    for sub_id, url in (
        (live.id, "https://live.example/a"),
        ("sub_ghost", "https://ghost.example/b"),
    ):
        upsert_discovered(
            conn,
            subscription_id=sub_id,
            board_id=None,
            item=FeedItem(guid=None, url=url, title=url, summary=None, published=None),
            now=now,
            module_id=None,
        )
    conn.commit()

    assert purge_orphaned_items(conn) == 1
    urls = [c.url for c in recent_tracked_items(conn, since=now.replace(year=2025))]
    assert urls == ["https://live.example/a"]
    assert purge_orphaned_items(conn) == 0  # idempotent


def test_scheduler_tick_purges_orphans_even_with_no_subscriptions(tmp_path: Path) -> None:
    """Owner 2026-07-13: with EVERY source deleted nothing is "due", so a purge
    living inside run_poll never ran — deleted sources' items sat in Today for a
    day. The tick now heals unconditionally, before the due-check."""
    from datetime import UTC, datetime

    from app.clients.mock import MockLLMClient
    from app.db.tracked_item_store import recent_tracked_items, upsert_discovered
    from app.tracking.feed import FeedItem
    from app.tracking.runtime import poll_due_subscriptions

    now = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)
    conn = init_db(str(tmp_path / "daily.db"))
    upsert_discovered(
        conn,
        subscription_id="sub_ghost",
        board_id=None,
        item=FeedItem(
            guid=None, url="https://ghost.example/a", title="x", summary=None, published=None
        ),
        now=now,
        module_id=None,
    )
    conn.commit()
    out = poll_due_subscriptions(
        conn,
        llm=MockLLMClient([]),
        fetch=lambda _u: b"",
        ingest=lambda req: (_ for _ in ()).throw(AssertionError("no ingest")),
        now=now,
    )
    assert out is None  # nothing due — and the orphan is STILL gone
    assert recent_tracked_items(conn, since=now.replace(year=2025)) == []
