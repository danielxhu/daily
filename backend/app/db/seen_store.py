"""Seen-items store (M7.6, SSOT §6.2 / §6.3).

The set-based dedup that answers *"have we already processed this item?"* — the
**single** thing that decides new vs. old (there is deliberately no `last_seen`
cursor: a cursor is unreliable for RSS reorder / homepage-diff, §6.3). Keys are
computed by `app.tracking.dedup`; this module is the plain DB membership over the
`seen_items(subscription_id, item_key)` table.

Scope: dedup only — no scheduler / poll loop (M7.7), no ingestion dispatch.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


def is_seen(conn: sqlite3.Connection, subscription_id: str, item_key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM seen_items WHERE subscription_id = ? AND item_key = ?",
        (subscription_id, item_key),
    ).fetchone()
    return row is not None


def mark_seen(
    conn: sqlite3.Connection,
    subscription_id: str,
    item_key: str,
    *,
    first_seen: datetime | None = None,
) -> bool:
    """Record an item key as seen (set semantics — INSERT OR IGNORE on the
    (subscription_id, item_key) PRIMARY KEY). Returns True iff newly inserted."""
    ts = (first_seen or datetime.now(UTC)).isoformat()
    cur = conn.execute(
        "INSERT OR IGNORE INTO seen_items (subscription_id, item_key, first_seen) VALUES (?, ?, ?)",
        (subscription_id, item_key, ts),
    )
    conn.commit()
    return cur.rowcount > 0


def unmark_seen(conn: sqlite3.Connection, subscription_id: str, item_key: str) -> bool:
    """Forget an item key so the NEXT poll re-discovers it as new (M14.5: a first
    check defers transcription items — deferral must re-queue, never skip for good).
    Returns True iff a row was removed."""
    cur = conn.execute(
        "DELETE FROM seen_items WHERE subscription_id = ? AND item_key = ?",
        (subscription_id, item_key),
    )
    conn.commit()
    return cur.rowcount > 0
