"""The enrichment backfill CLI (owner 2026-07-10): stored-text items get their
bilingual summary from the STORED excerpt (no re-fetch); account-level LLM
failures abort instead of burning retries item after item."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.db.engine import init_db
from app.db.tracked_item_store import upsert_discovered
from app.tracking.backfill import backfill
from app.tracking.feed import FeedItem
from tests.test_tracking_runtime import _KeyedLLM

NOW = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


def _seed(conn: sqlite3.Connection, url: str, *, excerpt: str | None, sub: str = "sub1") -> str:
    upsert_discovered(
        conn,
        subscription_id=sub,
        board_id="b1",
        item=FeedItem(guid=None, url=url, title=f"item {url[-1]}", summary=None, published=None),
        now=NOW,
        module_id=None,
    )
    row = conn.execute("SELECT id FROM tracked_items WHERE url = ?", (url,)).fetchone()
    if excerpt is not None:
        conn.execute(
            "UPDATE tracked_items SET content_excerpt = ?, status = 'fetched' WHERE id = ?",
            (excerpt, row["id"]),
        )
    conn.commit()
    return str(row["id"])


def test_backfill_summarizes_stored_text_only(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    with_text = _seed(conn, "https://x.example/1", excerpt="stored body one")
    _seed(conn, "https://x.example/2", excerpt=None, sub="sub2")  # skipped: nothing stored

    ok, failed = backfill(conn, _KeyedLLM())
    assert (ok, failed) == (1, 0)
    row = conn.execute("SELECT enrichment FROM tracked_items WHERE id = ?", (with_text,)).fetchone()
    assert row["enrichment"] is not None and "summary_zh" in row["enrichment"]
    # the no-text item stays untouched — backfill never fetches the network
    row = conn.execute(
        "SELECT enrichment FROM tracked_items WHERE url = 'https://x.example/2'"
    ).fetchone()
    assert row["enrichment"] is None


def test_backfill_aborts_on_an_account_level_failure(tmp_path: Path) -> None:
    class _BrokeLLM:
        calls = 0

        def complete_json(self, **_: object) -> dict[str, object]:
            type(self).calls += 1
            raise RuntimeError("Error code: 402 - Insufficient Balance")

    conn = init_db(str(tmp_path / "daily.db"))
    _seed(conn, "https://x.example/1", excerpt="one")
    _seed(conn, "https://x.example/2", excerpt="two", sub="sub2")

    ok, failed = backfill(conn, _BrokeLLM())
    assert ok == 0 and failed == 1  # aborted after the FIRST balance error
    assert _BrokeLLM.calls == 1
