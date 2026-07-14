"""Day-1 source-pack auto-adoption (M14.1, owner 2026-07-06).

The owner's call after real-mode acceptance: "打开的时候自动给用户弹出内容,然后
用户在之后自主决定删除还是留下" — a cold start should not face an empty Today and
a manual adopt-each-source chore. On the FIRST open, the built-in starter pack is
adopted wholesale as subscriptions (each entry keeps its mode + preset topic
board); the user then trims. This stays inside the D8 red line: the pack is the
STATIC curated list — never topic discovery.

One-time by design: a `source_pack_seeded` flag in `app_flags` records that
seeding happened. The flag — not the subscription count — gates re-seeding, so a
user who deliberately deletes every source keeps an empty list (their choice is
never overridden by a refill).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from app.db.subscription_store import create_subscription
from app.schemas.models import Subscription
from app.source_pack import default_source_pack

SEEDED_FLAG = "source_pack_seeded"


def _flag_set(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT 1 FROM app_flags WHERE key = ?", (key,)).fetchone() is not None


def _set_flag(conn: sqlite3.Connection, key: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO app_flags (key, value, created_at) VALUES (?, '1', ?)",
        (key, datetime.now(UTC).isoformat()),
    )
    conn.commit()


def adopt_source_pack(conn: sqlite3.Connection) -> list[Subscription]:
    """Adopt the whole starter pack as subscriptions, ONCE ever per database.
    Returns the created subscriptions, or [] when seeding already happened —
    including after the user deleted everything (deliberate, never re-filled)."""
    if _flag_set(conn, SEEDED_FLAG):
        return []
    created = [
        create_subscription(
            conn,
            input_url=entry.url,
            mode=entry.mode,
            board_id=entry.board_id,
        )
        for entry in default_source_pack()
    ]
    _set_flag(conn, SEEDED_FLAG)
    return created
