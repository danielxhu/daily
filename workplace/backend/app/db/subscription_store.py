"""Subscription store (M7.1, SSOT FR-3 / §7).

A subscription is a pollable source (feed / homepage / channel URL) attached to a
board. This module is plain CRUD; the poll machinery fills the runtime/health
fields later (M7.6 dedup, M7.7 scheduler, M7.8 health). A fresh subscription has
never been polled and is healthy.

Scope red line (§2.2): tracking polls **operator-given** sources — it never
discovers sources by topic. Nothing here searches the web for new sources.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Literal

from app.schemas.models import Subscription, SubscriptionFailureKind

SubscriptionMode = Literal["direct", "autodiscover", "platform", "homepage_diff"]

# Health policy (§6.6): after this many consecutive isolated failures a subscription
# is marked unhealthy and its poll interval backs off exponentially, capped at 24h.
UNHEALTHY_AFTER = 3
BACKOFF_CAP_MINUTES = 24 * 60


def _backoff(interval_minutes: int) -> int:
    return min(interval_minutes * 2, BACKOFF_CAP_MINUTES)


_COLUMNS = (
    "id, board_id, module_id, input_url, feed_url, mode, interval_minutes, last_polled,"
    " last_seen_item_key_for_display, consecutive_failures, health, last_error,"
    " subscription_failure_kind"
)


def _row_to_subscription(row: sqlite3.Row) -> Subscription:
    last_polled = row["last_polled"]
    return Subscription(
        id=row["id"],
        board_id=row["board_id"],
        module_id=row["module_id"],
        input_url=row["input_url"],
        feed_url=row["feed_url"],
        mode=row["mode"],
        interval_minutes=row["interval_minutes"],
        last_polled=datetime.fromisoformat(last_polled) if last_polled else None,
        last_seen_item_key_for_display=row["last_seen_item_key_for_display"],
        consecutive_failures=row["consecutive_failures"],
        health=row["health"],
        last_error=row["last_error"],
        subscription_failure_kind=row["subscription_failure_kind"],
    )


def create_subscription(
    conn: sqlite3.Connection,
    *,
    input_url: str,
    mode: SubscriptionMode,
    board_id: str | None = None,
    module_id: str | None = None,
    feed_url: str | None = None,
    interval_minutes: int = 60,
) -> Subscription:
    """Create a subscription with a generated id. Health/runtime fields start fresh
    (never polled, healthy, no failures); the poll loop fills them later."""
    sub = Subscription(
        id=uuid.uuid4().hex,
        board_id=board_id,
        module_id=module_id,
        input_url=input_url,
        feed_url=feed_url,
        mode=mode,
        interval_minutes=interval_minutes,
        last_polled=None,
        last_seen_item_key_for_display=None,
    )
    conn.execute(
        f"INSERT INTO subscriptions ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sub.id,
            sub.board_id,
            sub.module_id,
            sub.input_url,
            sub.feed_url,
            sub.mode,
            sub.interval_minutes,
            None,  # last_polled
            None,  # last_seen_item_key_for_display
            sub.consecutive_failures,
            sub.health,
            sub.last_error,
            sub.subscription_failure_kind,
        ),
    )
    conn.commit()
    return sub


def get_subscription(conn: sqlite3.Connection, subscription_id: str) -> Subscription | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM subscriptions WHERE id = ?", (subscription_id,)
    ).fetchone()
    return _row_to_subscription(row) if row is not None else None


def list_subscriptions(
    conn: sqlite3.Connection, *, board_id: str | None = None
) -> list[Subscription]:
    """All subscriptions, or just one board's when `board_id` is given."""
    if board_id is None:
        rows = conn.execute(f"SELECT {_COLUMNS} FROM subscriptions ORDER BY input_url").fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM subscriptions WHERE board_id = ? ORDER BY input_url",
            (board_id,),
        ).fetchall()
    return [_row_to_subscription(r) for r in rows]


def purge_subscription_items(conn: sqlite3.Connection, subscription_ids: list[str]) -> None:
    """Remove everything a subscription discovered (owner 2026-07-10: "把 source
    删掉了,在今日里面还能看到他的消息" — a removed source must take its items with
    it): tracked items, their fact-lineage rows, and the seen-set. The user's own
    notes are board-level and untouched. No commit — callers commit their unit."""
    if not subscription_ids:
        return
    marks = ", ".join("?" for _ in subscription_ids)
    conn.execute(
        "DELETE FROM tracked_item_facts WHERE item_id IN "
        f"(SELECT id FROM tracked_items WHERE subscription_id IN ({marks}))",
        subscription_ids,
    )
    conn.execute(f"DELETE FROM tracked_items WHERE subscription_id IN ({marks})", subscription_ids)
    conn.execute(f"DELETE FROM seen_items WHERE subscription_id IN ({marks})", subscription_ids)


def purge_orphaned_items(conn: sqlite3.Connection) -> int:
    """Self-healing sweep (owner 2026-07-10): remove items whose subscription no
    longer exists — deletions made before the cascade existed (or by an older
    build) left orphans that kept showing in Today. Runs at every poll start;
    returns the number of items removed. Commits (it is its own unit)."""
    orphan = (
        "SELECT id FROM tracked_items WHERE subscription_id NOT IN (SELECT id FROM subscriptions)"
    )
    conn.execute(f"DELETE FROM tracked_item_facts WHERE item_id IN ({orphan})")
    cur = conn.execute(
        "DELETE FROM tracked_items WHERE subscription_id NOT IN (SELECT id FROM subscriptions)"
    )
    conn.execute(
        "DELETE FROM seen_items WHERE subscription_id NOT IN (SELECT id FROM subscriptions)"
    )
    conn.commit()
    return cur.rowcount


def delete_subscription(conn: sqlite3.Connection, subscription_id: str) -> bool:
    """Delete a subscription AND everything it discovered (items / seen-set /
    lineage); returns True if the subscription existed."""
    purge_subscription_items(conn, [subscription_id])
    cur = conn.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
    conn.commit()
    return cur.rowcount > 0


def record_poll_success(
    conn: sqlite3.Connection, subscription_id: str, *, polled_at: datetime | None = None
) -> None:
    """A clean poll resets the health bookkeeping (§6.6): zero failures, healthy,
    clear the last error/kind. The interval is left as-is (a backed-off interval is
    not auto-restored — §6.6 only specifies resetting the failure count/health)."""
    ts = (polled_at or datetime.now(UTC)).isoformat()
    conn.execute(
        "UPDATE subscriptions SET consecutive_failures = 0, health = 'ok',"
        " last_error = NULL, subscription_failure_kind = NULL, last_polled = ?"
        " WHERE id = ?",
        (ts, subscription_id),
    )
    conn.commit()


def record_poll_failure(
    conn: sqlite3.Connection,
    subscription_id: str,
    kind: SubscriptionFailureKind,
    error: str,
    *,
    polled_at: datetime | None = None,
) -> Subscription | None:
    """An isolated failure increments the counter and records the typed kind + error
    (§6.6). At/after `UNHEALTHY_AFTER` consecutive failures the subscription is marked
    unhealthy and its interval backs off (doubles, capped). Returns the updated row,
    or None if the subscription is gone."""
    sub = get_subscription(conn, subscription_id)
    if sub is None:
        return None
    failures = sub.consecutive_failures + 1
    unhealthy = failures >= UNHEALTHY_AFTER
    health = "unhealthy" if unhealthy else "ok"
    interval = _backoff(sub.interval_minutes) if unhealthy else sub.interval_minutes
    ts = (polled_at or datetime.now(UTC)).isoformat()
    conn.execute(
        "UPDATE subscriptions SET consecutive_failures = ?, health = ?, last_error = ?,"
        " subscription_failure_kind = ?, interval_minutes = ?, last_polled = ?"
        " WHERE id = ?",
        (failures, health, error, kind, interval, ts, subscription_id),
    )
    conn.commit()
    return get_subscription(conn, subscription_id)


def set_subscription_module(
    conn: sqlite3.Connection, subscription_id: str, module_id: str | None
) -> Subscription | None:
    """Assign a source to a module within its board (M15.1) — or un-group with
    None. Returns the updated row, or None when the subscription doesn't exist.
    Board consistency (the module must belong to the source's board) is the API
    layer's check; this is plain storage."""
    conn.execute(
        "UPDATE subscriptions SET module_id = ? WHERE id = ?", (module_id, subscription_id)
    )
    conn.commit()
    return get_subscription(conn, subscription_id)
