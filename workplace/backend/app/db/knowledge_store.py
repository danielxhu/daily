"""Per-board `KnowledgeNote`s (verification engine removed 2026-07-13).

Two user-authored kinds remain: `user_note` (a plain note, e.g. from an item's
detail page) and `saved_check` (notes saved from the retired check era — still
the user's own words, still searchable). Both ground the on-demand knowledge
answer. `KnowledgeNote.regenerable=False` for user content."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Literal

from app.schemas.models import KnowledgeNote

# the human note kinds the notes API accepts; ai_distilled is generated in M6.4,
# not posted. saved_check (M13.2) = the user-curated text of a /verify result —
# user-authored (negotiated with the model, but the USER edits and confirms), so
# it goes through the same human-note path.
HumanNoteKind = Literal["user_note", "saved_check"]


def _row_to_note(row: sqlite3.Row) -> KnowledgeNote:
    return KnowledgeNote(
        id=row["id"],
        board_id=row["board_id"],
        kind=row["kind"],
        content=row["content"],
        citations=json.loads(row["citations_json"]),
        is_synthesized=bool(row["is_synthesized"]),
        regenerable=bool(row["regenerable"]),
        created_at=row["created_at"],
    )


def persist_note(conn: sqlite3.Connection, note: KnowledgeNote) -> None:
    """Insert a pre-built `KnowledgeNote` (any kind). Used by `create_note` for human
    notes and by the M6.4 distiller for `ai_distilled` notes."""
    conn.execute(
        "INSERT INTO knowledge_notes "
        "(id, board_id, kind, content, citations_json, is_synthesized, regenerable, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            note.id,
            note.board_id,
            note.kind,
            note.content,
            json.dumps(note.citations),
            int(note.is_synthesized),
            int(note.regenerable),
            note.created_at.isoformat(),
        ),
    )
    conn.commit()


def create_note(
    conn: sqlite3.Connection,
    board_id: str,
    kind: HumanNoteKind,
    content: str,
    *,
    citations: list[str] | None = None,
) -> KnowledgeNote:
    """Create a human knowledge note (`pinned_fact` / `user_note`). User-authored, so
    not synthesized and not a regenerable cache."""
    note = KnowledgeNote(
        id=uuid.uuid4().hex,
        board_id=board_id,
        kind=kind,
        content=content,
        citations=citations or [],
        is_synthesized=False,
        regenerable=False,
        created_at=datetime.now(UTC),
    )
    persist_note(conn, note)
    return note


def list_notes(conn: sqlite3.Connection, board_id: str) -> list[KnowledgeNote]:
    rows = conn.execute(
        "SELECT id, board_id, kind, content, citations_json, is_synthesized, regenerable, "
        "created_at FROM knowledge_notes WHERE board_id = ? ORDER BY created_at",
        (board_id,),
    ).fetchall()
    return [_row_to_note(r) for r in rows]


# CJK Unified Ideographs (+ Extension A) — the ranges bilingual zh queries live in
_CJK_RUN = re.compile(r"[一-鿿㐀-䶿]+")
_ASCII_WORD = re.compile(r"[a-zA-Z0-9_]+")


def _query_tokens(query: str) -> set[str]:
    """Bilingual query tokens (M13.2 review blocker): Chinese has no word spaces, so
    a `\\w+`-style split makes zh queries unusable ('并购' → filtered as too short;
    '并购批准了吗' → one 6-char token that whole-substring-misses). CJK runs become
    overlapping bigrams (a 1-char run counts as itself) so word order inside the
    query doesn't matter; ASCII words keep the ≥3-char rule."""
    tokens: set[str] = set()
    for run in _CJK_RUN.findall(query):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    for word in _ASCII_WORD.findall(query.lower()):
        if len(word) >= 3:
            tokens.add(word)
    return tokens


def search_saved_notes(
    conn: sqlite3.Connection, query: str, *, limit: int = 5
) -> list[KnowledgeNote]:
    """Keyword search over the user's OWN notes (M13.2, widened by M16.2 review):
    `saved_check` + `user_note` — everything the user typed or deliberately saved
    is searchable and can ground the on-demand answer (FR-15). Deliberately NOT
    searched: `ai_distilled` (a regenerable cache, not user content) and
    `pinned_fact` (verification-derived text — dormant with the fact layer in
    v0.13; it still displays in the board Notes region). Token-overlap scoring
    (CJK-aware — zh bigrams + en words), ranked by distinct query tokens hit then
    recency. Deterministic and ML-free. Single-operator scale, so scoring in
    Python is fine."""
    return _keyword_search(conn, query, kinds=("saved_check", "user_note"), limit=limit)


def _keyword_search(
    conn: sqlite3.Connection, query: str, *, kinds: tuple[str, ...], limit: int
) -> list[KnowledgeNote]:
    tokens = _query_tokens(query)
    if not tokens:
        return []
    placeholders = ", ".join("?" for _ in kinds)
    rows = conn.execute(
        "SELECT id, board_id, kind, content, citations_json, is_synthesized, regenerable, "
        f"created_at FROM knowledge_notes WHERE kind IN ({placeholders})",
        kinds,
    ).fetchall()
    scored: list[tuple[int, str, KnowledgeNote]] = []
    for row in rows:
        content = str(row["content"]).lower()
        score = sum(1 for tok in tokens if tok in content)
        if score > 0:
            scored.append((score, str(row["created_at"]), _row_to_note(row)))
    # two stable passes: newest first, then most-distinct-tokens-hit first
    scored.sort(key=lambda item: item[1], reverse=True)
    scored.sort(key=lambda item: -item[0])
    return [note for _, _, note in scored[:limit]]


def delete_note(conn: sqlite3.Connection, board_id: str, note_id: str) -> bool:
    """Delete a note scoped to its board — the path's `board_id` is authoritative, so
    a note cannot be deleted through the wrong board (FR-15 per-board view). Returns
    False if the note doesn't exist in that board."""
    cur = conn.execute(
        "DELETE FROM knowledge_notes WHERE id = ? AND board_id = ?", (note_id, board_id)
    )
    conn.commit()
    return cur.rowcount > 0
