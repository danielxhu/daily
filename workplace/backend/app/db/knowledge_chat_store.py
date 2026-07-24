"""Persisted knowledge Q&A conversations.

Every ask on the Knowledge page lives in a chat: open an old one to re-read it,
or keep asking and the answer call sees the earlier turns. One JSON messages
array per chat — at single-operator scale a conversation is read and written
whole, so a message table would only add joins.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime

from app.schemas.models import DiscussMessage, KnowledgeChat, KnowledgeChatSummary

_TITLE_CHARS = 60


def _row_to_chat(row: sqlite3.Row) -> KnowledgeChat:
    messages = [DiscussMessage(**m) for m in json.loads(row["messages"])]
    return KnowledgeChat(
        id=row["id"],
        title=row["title"],
        messages=messages,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def list_chats(conn: sqlite3.Connection) -> list[KnowledgeChatSummary]:
    rows = conn.execute(
        "SELECT id, title, messages, updated_at FROM knowledge_chats ORDER BY updated_at DESC"
    ).fetchall()
    return [
        KnowledgeChatSummary(
            id=r["id"],
            title=r["title"],
            updated_at=datetime.fromisoformat(r["updated_at"]),
            message_count=len(json.loads(r["messages"])),
        )
        for r in rows
    ]


def get_chat(conn: sqlite3.Connection, chat_id: str) -> KnowledgeChat | None:
    row = conn.execute("SELECT * FROM knowledge_chats WHERE id = ?", (chat_id,)).fetchone()
    return _row_to_chat(row) if row else None


def create_chat(
    conn: sqlite3.Connection, *, messages: list[DiscussMessage], now: datetime
) -> KnowledgeChat:
    """New chat titled after its first user turn (the question IS the title)."""
    first_user = next((m.content for m in messages if m.role == "user"), "")
    title = " ".join(first_user.split())[:_TITLE_CHARS] or "(untitled)"
    chat_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO knowledge_chats (id, title, messages, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            chat_id,
            title,
            json.dumps([m.model_dump() for m in messages], ensure_ascii=False),
            now.isoformat(),
            now.isoformat(),
        ),
    )
    conn.commit()
    chat = get_chat(conn, chat_id)
    assert chat is not None
    return chat


def append_messages(
    conn: sqlite3.Connection, chat_id: str, new_messages: list[DiscussMessage], *, now: datetime
) -> KnowledgeChat | None:
    chat = get_chat(conn, chat_id)
    if chat is None:
        return None
    combined = [*chat.messages, *new_messages]
    conn.execute(
        "UPDATE knowledge_chats SET messages = ?, updated_at = ? WHERE id = ?",
        (
            json.dumps([m.model_dump() for m in combined], ensure_ascii=False),
            now.isoformat(),
            chat_id,
        ),
    )
    conn.commit()
    return get_chat(conn, chat_id)


def delete_chat(conn: sqlite3.Connection, chat_id: str) -> bool:
    cur = conn.execute("DELETE FROM knowledge_chats WHERE id = ?", (chat_id,))
    conn.commit()
    return cur.rowcount > 0
