"""Knowledge-module store (M15.1, v0.12 / FR-15).

Modules are the user-named grouping INSIDE a board: board → module → source →
item → fact/note/saved_check. Membership lives on the source (`subscriptions.
module_id`) and is stamped onto its items at discovery. Deleting a module only
UN-groups (module_id → NULL on its subscriptions and tracked items) — content is
the user's; a grouping change never deletes sources, items, facts, or notes.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

from app.schemas.models import KnowledgeModule


def create_module(conn: sqlite3.Connection, *, board_id: str, name: str) -> KnowledgeModule:
    module = KnowledgeModule(
        id=uuid.uuid4().hex, board_id=board_id, name=name, created_at=datetime.now(UTC)
    )
    conn.execute(
        "INSERT INTO knowledge_modules (id, board_id, name, created_at) VALUES (?, ?, ?, ?)",
        (module.id, module.board_id, module.name, module.created_at.isoformat()),
    )
    conn.commit()
    return module


def list_modules(conn: sqlite3.Connection, board_id: str) -> list[KnowledgeModule]:
    rows = conn.execute(
        "SELECT id, board_id, name, created_at FROM knowledge_modules"
        " WHERE board_id = ? ORDER BY created_at",
        (board_id,),
    ).fetchall()
    return [
        KnowledgeModule(
            id=r["id"],
            board_id=r["board_id"],
            name=r["name"],
            created_at=datetime.fromisoformat(r["created_at"]),
        )
        for r in rows
    ]


def get_module(conn: sqlite3.Connection, module_id: str) -> KnowledgeModule | None:
    r = conn.execute(
        "SELECT id, board_id, name, created_at FROM knowledge_modules WHERE id = ?",
        (module_id,),
    ).fetchone()
    if r is None:
        return None
    return KnowledgeModule(
        id=r["id"],
        board_id=r["board_id"],
        name=r["name"],
        created_at=datetime.fromisoformat(r["created_at"]),
    )


def delete_module(conn: sqlite3.Connection, module_id: str) -> bool:
    """Delete the grouping, never the content: member sources and items fall back
    to ungrouped (module_id NULL). Returns False when the module doesn't exist."""
    conn.execute("UPDATE subscriptions SET module_id = NULL WHERE module_id = ?", (module_id,))
    conn.execute("UPDATE tracked_items SET module_id = NULL WHERE module_id = ?", (module_id,))
    cur = conn.execute("DELETE FROM knowledge_modules WHERE id = ?", (module_id,))
    conn.commit()
    return cur.rowcount > 0
