"""Board store (M6.1, SSOT FR-15 / §7).

A board is a single-operator **topic collection** (finance / semiconductors /
policy …), NOT a user account. Facts and sources link to boards by
`board_id` / `board_ids`; the fact store itself stays single, shared, and deduped
(M6.2). This module is plain CRUD over the `boards` table.

Scope red line (FR-15 / §2.2): there is **no auth, no users, no permissions** — V1
is a local single-operator app. Nothing here creates or reads a user/account table.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

from app.schemas.models import Board


def _row_to_board(row: sqlite3.Row) -> Board:
    return Board(id=row["id"], name=row["name"], created_at=row["created_at"])


def create_board(conn: sqlite3.Connection, name: str) -> Board:
    """Create a topic board with a generated id + creation timestamp."""
    board = Board(id=uuid.uuid4().hex, name=name, created_at=datetime.now(UTC))
    conn.execute(
        "INSERT INTO boards (id, name, created_at) VALUES (?, ?, ?)",
        (board.id, board.name, board.created_at.isoformat()),
    )
    conn.commit()
    return board


def get_board(conn: sqlite3.Connection, board_id: str) -> Board | None:
    row = conn.execute(
        "SELECT id, name, created_at FROM boards WHERE id = ?", (board_id,)
    ).fetchone()
    return _row_to_board(row) if row is not None else None


def list_boards(conn: sqlite3.Connection) -> list[Board]:
    rows = conn.execute("SELECT id, name, created_at FROM boards ORDER BY created_at").fetchall()
    return [_row_to_board(r) for r in rows]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def delete_board(conn: sqlite3.Connection, board_id: str) -> bool:
    """Delete a board; returns True if a row was removed. The shared fact store is
    untouched — a board is only a grouping view (M6.2).

    Board-scoped subscriptions (tracking domain, M7.1) are cleaned up here in the
    app layer rather than via a DB foreign key: a cross-domain FK would break the
    domain-independent migration rule (X0.6). Guarded with a table check so a
    board-only DB (tracking not migrated) still deletes cleanly."""
    if _table_exists(conn, "subscriptions"):
        # the board's sources go — and (2026-07-10) each source takes its
        # discovered items / seen-set / lineage with it, same as a direct removal
        from app.db.subscription_store import purge_subscription_items

        ids = [
            str(r["id"])
            for r in conn.execute(
                "SELECT id FROM subscriptions WHERE board_id = ?", (board_id,)
            ).fetchall()
        ]
        purge_subscription_items(conn, ids)
        conn.execute("DELETE FROM subscriptions WHERE board_id = ?", (board_id,))
    cur = conn.execute("DELETE FROM boards WHERE id = ?", (board_id,))
    conn.commit()
    return cur.rowcount > 0
