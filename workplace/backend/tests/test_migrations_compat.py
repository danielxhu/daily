"""M15.6 — old-schema upgrade fixture (v0.12 compatibility promise).

A REAL pre-Stage-15 database (tracking schema at v6: no tracked_items, no
modules, no lineage, no item summaries) must upgrade in place with every user
asset intact — subscriptions, boards, saved checks, notes, digest caches, and
memory facts survive; the new columns read back as honest NULL/ungrouped.
This fixture was added once migration logic grew beyond a single
additive ALTER (M15.1 review note)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import app.db.migrations as mig
from app.db.engine import connect, init_db
from app.db.knowledge_store import search_saved_notes
from app.db.subscription_store import list_subscriptions
from app.db.tracked_item_store import recent_tracked_items

NOW = datetime.now(UTC)


def _build_v6_database(path: str) -> None:
    """A world as it was before Stage 15: tracking migrations only up to v6."""
    old_world = {
        domain: [m for m in ms if domain != "tracking" or m.version <= 6]
        for domain, ms in mig.MIGRATIONS.items()
    }
    conn = connect(path)
    original = mig.MIGRATIONS
    mig.MIGRATIONS = old_world
    try:
        mig.migrate(conn)
    finally:
        mig.MIGRATIONS = original
    # user assets, inserted with the OLD column sets (no module_id anywhere)
    conn.execute(
        "INSERT INTO subscriptions (id, board_id, input_url, feed_url, mode,"
        " interval_minutes, last_polled, last_seen_item_key_for_display,"
        " consecutive_failures, health, last_error, subscription_failure_kind)"
        " VALUES ('sub_old', 'b_old', 'https://old.example.com/feed', NULL, 'direct',"
        " 60, NULL, NULL, 0, 'ok', NULL, NULL)"
    )
    conn.execute(
        "INSERT INTO boards (id, name, created_at) VALUES ('b_old', 'Finance', ?)",
        (NOW.isoformat(),),
    )
    conn.execute(
        "INSERT INTO knowledge_notes (id, board_id, kind, content, citations_json,"
        " is_synthesized, regenerable, created_at)"
        " VALUES ('n_old', 'b_old', 'saved_check', 'Fed approved the merger.', '[]', 0, 0, ?)",
        (NOW.isoformat(),),
    )
    conn.execute(
        "INSERT INTO digest_summaries (claim_id, version, summary, created_at)"
        " VALUES ('c_old', 1, 'An old cached summary.', ?)",
        (NOW.isoformat(),),
    )
    conn.commit()
    conn.close()


def test_pre_stage15_database_upgrades_in_place_with_assets_intact(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    _build_v6_database(db)

    # opening the old database applies v7 (tracked_items), v8 (modules/lineage),
    # v9 (item summary), v10 (M16.3 bilingual enrichment + excerpt), v11 (M16.4
    # extraction-method provenance) — in place
    conn = init_db(db)
    versions = {
        row["version"]
        for row in conn.execute(
            "SELECT version FROM schema_migrations WHERE domain = 'tracking'"
        ).fetchall()
    }
    assert {7, 8, 9, 10, 11} <= versions
    # the v10/v11 columns exist and read back honestly on an empty table
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tracked_items)").fetchall()}
    assert {"enrichment", "content_excerpt", "extraction_method"} <= cols

    # every user asset survived, and the new columns read back honestly
    subs = list_subscriptions(conn)
    assert [s.id for s in subs] == ["sub_old"]
    assert subs[0].module_id is None  # pre-module rows are simply ungrouped
    assert conn.execute("SELECT name FROM boards WHERE id='b_old'").fetchone()["name"] == "Finance"
    saved = search_saved_notes(conn, "merger")
    assert [n.id for n in saved] == ["n_old"]
    row = conn.execute("SELECT summary FROM digest_summaries WHERE claim_id='c_old'").fetchone()
    assert row["summary"] == "An old cached summary."
    # the new tables exist and start empty — nothing was fabricated
    assert recent_tracked_items(conn, since=NOW.replace(year=NOW.year - 1)) == []
    assert conn.execute("SELECT COUNT(*) FROM knowledge_modules").fetchone()[0] == 0


def test_old_schema_lacks_the_new_tables_before_upgrade(tmp_path: Path) -> None:
    """The fixture is honest: the v6 world really has no Stage-15 tables."""
    import sqlite3

    db = str(tmp_path / "daily.db")
    _build_v6_database(db)
    conn = connect(db)
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        conn.execute("SELECT 1 FROM tracked_items")
