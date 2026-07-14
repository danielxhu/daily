"""M15.1 — knowledge modules + the board→module→source→item hierarchy (v0.12 / FR-15).

Modules are user-named groupings inside a board; membership lives on the source
and is stamped onto items at discovery. Deleting a module only UN-groups — it
never deletes sources, items, facts, or notes. Pre-v8 rows (no module) stay
readable as ungrouped."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.board_store import create_board
from app.db.engine import init_db
from app.db.knowledge_module_store import create_module, delete_module, list_modules
from app.db.subscription_store import (
    create_subscription,
    get_subscription,
    set_subscription_module,
)
from app.db.tracked_item_store import recent_tracked_items, upsert_discovered
from app.main import create_app, get_db
from app.tracking.feed import FeedItem

NOW = datetime.now(UTC)


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


# --- store -------------------------------------------------------------------


def test_module_crud_and_membership(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    board = create_board(conn, "Finance")
    module = create_module(conn, board_id=board.id, name="Rates")
    assert [m.name for m in list_modules(conn, board.id)] == ["Rates"]

    sub = create_subscription(
        conn,
        input_url="https://www.sec.gov/news",
        mode="direct",
        board_id=board.id,
        module_id=module.id,
    )
    assert sub.module_id == module.id
    # re-assignment and un-grouping
    assert (updated := set_subscription_module(conn, sub.id, None)) is not None
    assert updated.module_id is None


def test_items_inherit_the_source_module_at_discovery(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    board = create_board(conn, "Finance")
    module = create_module(conn, board_id=board.id, name="Rates")
    upsert_discovered(
        conn,
        subscription_id="sub1",
        board_id=board.id,
        item=FeedItem(guid=None, url="https://x.com/a", title="A", summary=None, published=None),
        now=NOW,
        module_id=module.id,
    )
    card = recent_tracked_items(conn, since=NOW - timedelta(days=1))[0]
    assert card.module_id == module.id and card.board_id == board.id


def test_deleting_a_module_ungroups_but_never_deletes_content(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    board = create_board(conn, "Finance")
    module = create_module(conn, board_id=board.id, name="Rates")
    sub = create_subscription(
        conn,
        input_url="https://www.sec.gov/news",
        mode="direct",
        board_id=board.id,
        module_id=module.id,
    )
    upsert_discovered(
        conn,
        subscription_id=sub.id,
        board_id=board.id,
        item=FeedItem(guid=None, url="https://x.com/a", title="A", summary=None, published=None),
        now=NOW,
        module_id=module.id,
    )
    assert delete_module(conn, module.id) is True
    assert list_modules(conn, board.id) == []
    # the source and the item both survive, now ungrouped
    refreshed = get_subscription(conn, sub.id)
    assert refreshed is not None and refreshed.module_id is None
    cards = recent_tracked_items(conn, since=NOW - timedelta(days=1))
    assert len(cards) == 1 and cards[0].module_id is None


def test_pre_module_rows_stay_readable_as_ungrouped(tmp_path: Path) -> None:
    """v0.12 compatibility promise: rows created before v8 (no module concept)
    read back with module_id None — nothing about them needs migrating."""
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(conn, input_url="https://old.example.com", mode="direct")
    assert sub.module_id is None
    upsert_discovered(
        conn,
        subscription_id=sub.id,
        board_id=None,
        item=FeedItem(
            guid=None, url="https://old.example.com/1", title=None, summary=None, published=None
        ),
        now=NOW,
    )
    card = recent_tracked_items(conn, since=NOW - timedelta(days=1))[0]
    assert card.module_id is None and card.status == "new"


# --- API ---------------------------------------------------------------------


def test_module_endpoints_create_list_delete_and_assign(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    board = create_board(conn, "Finance")
    other_board = create_board(conn, "Tech")
    sub = create_subscription(
        conn, input_url="https://www.sec.gov/news", mode="direct", board_id=board.id
    )
    conn.close()
    client = _client(db)

    # create + list
    res = client.post(f"/boards/{board.id}/modules", json={"name": "Rates"})
    assert res.status_code == 201
    module_id = res.json()["id"]
    assert [m["name"] for m in client.get(f"/boards/{board.id}/modules").json()] == ["Rates"]
    # honest errors
    assert client.post(f"/boards/{board.id}/modules", json={"name": "  "}).status_code == 400
    assert client.post("/boards/nope/modules", json={"name": "X"}).status_code == 404

    # assign the source to the module; a cross-board module is refused
    res = client.put(f"/subscriptions/{sub.id}/module", json={"module_id": module_id})
    assert res.status_code == 200 and res.json()["module_id"] == module_id
    other = client.post(f"/boards/{other_board.id}/modules", json={"name": "Chips"}).json()
    res = client.put(f"/subscriptions/{sub.id}/module", json={"module_id": other["id"]})
    assert res.status_code == 400
    # un-group with None
    res = client.put(f"/subscriptions/{sub.id}/module", json={"module_id": None})
    assert res.status_code == 200 and res.json()["module_id"] is None

    # delete → 204; content endpoints still work
    assert client.delete(f"/modules/{module_id}").status_code == 204
    assert client.delete(f"/modules/{module_id}").status_code == 404
    assert client.get(f"/boards/{board.id}/modules").json() == []


def test_subscription_create_validates_module_board_consistency(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    board = create_board(conn, "Finance")
    other_board = create_board(conn, "Tech")
    module = create_module(conn, board_id=other_board.id, name="Chips")
    conn.close()
    client = _client(db)
    res = client.post(
        "/subscriptions",
        json={
            "input_url": "https://x.com/feed",
            "mode": "direct",
            "board_id": board.id,
            "module_id": module.id,  # belongs to Tech, not Finance
        },
    )
    assert res.status_code == 400
    res = client.post(
        "/subscriptions",
        json={"input_url": "https://x.com/feed", "mode": "direct", "module_id": "nope"},
    )
    assert res.status_code == 404
