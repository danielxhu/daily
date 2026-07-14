"""M14.1 — Day-1 source-pack auto-adoption (owner 2026-07-06).

Covers: the whole pack becomes subscriptions (modes + preset boards intact), the
one-time flag (a second adopt is a no-op), and the red line the flag exists for —
a user who deleted every subscription is NEVER force-refilled.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.engine import init_db
from app.db.subscription_store import delete_subscription, list_subscriptions
from app.main import create_app, get_db
from app.source_pack import default_source_pack
from app.tracking.seed import adopt_source_pack


def test_adopt_seeds_the_whole_pack_once(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    created = adopt_source_pack(conn)
    pack = default_source_pack()
    assert len(created) == len(pack)
    # each subscription keeps its pack entry's mode + preset topic board
    by_url = {s.input_url: s for s in created}
    for entry in pack:
        sub = by_url[entry.url]
        assert sub.mode == entry.mode and sub.board_id == entry.board_id
    assert len(list_subscriptions(conn)) == len(pack)

    # second adopt: no-op — never a duplicate pile of subscriptions
    assert adopt_source_pack(conn) == []
    assert len(list_subscriptions(conn)) == len(pack)
    conn.close()


def test_adopt_never_refills_after_a_deliberate_clean_out(tmp_path: Path) -> None:
    """The owner's boundary: users decide what to delete or keep — deleting every
    source is a choice, and the app must not push the pack back in."""
    conn = init_db(str(tmp_path / "daily.db"))
    for sub in adopt_source_pack(conn):
        assert delete_subscription(conn, sub.id)
    assert list_subscriptions(conn) == []

    assert adopt_source_pack(conn) == []  # flag, not count, gates re-seeding
    assert list_subscriptions(conn) == []
    conn.close()


def _db_override(db_path: str) -> Callable[[], Iterator[sqlite3.Connection]]:
    def _get_db() -> Iterator[sqlite3.Connection]:
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    return _get_db


def test_adopt_endpoint_reports_seeded_then_clean_slate(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    init_db(db).close()
    app = create_app()
    app.dependency_overrides[get_db] = _db_override(db)
    client = TestClient(app)

    first = client.post("/source-pack/adopt").json()
    assert first["seeded"] is True
    assert len(first["subscriptions"]) == len(default_source_pack())
    assert first["subscriptions"][0]["board_id"] is not None  # boards ride along

    # the second call reports the deliberate no-op so the UI keeps the empty state
    second = client.post("/source-pack/adopt").json()
    assert second == {"seeded": False, "subscriptions": []}
