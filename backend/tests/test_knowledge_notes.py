"""Per-board knowledge notes (engine removed 2026-07-13): the two user-authored
kinds — `user_note` and `saved_check` — stored verbatim, board-scoped, deletable
only through their own board."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.board_store import create_board
from app.db.engine import init_db
from app.db.knowledge_store import create_note, list_notes
from app.main import create_app, get_db, get_llm


def _db_override(db_path: str) -> Callable[[], Iterator[sqlite3.Connection]]:
    def _get_db() -> Iterator[sqlite3.Connection]:
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    return _get_db


def _client_with_board(tmp_path: Path) -> tuple[TestClient, str]:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    board = create_board(conn, "Finance")
    conn.close()
    app = create_app()
    app.dependency_overrides[get_db] = _db_override(db)
    return TestClient(app), board.id


def test_store_create_list_delete(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    board = create_board(conn, "Finance")
    note = create_note(conn, board.id, "user_note", "watch the July filing")
    saved = create_note(conn, board.id, "saved_check", "Fed approved the merger")
    notes = list_notes(conn, board.id)
    assert {n.kind for n in notes} == {"user_note", "saved_check"}
    assert all(n.regenerable is False for n in notes)  # user content, never a cache
    assert note.board_id == board.id and saved.board_id == board.id


def test_notes_endpoint_roundtrip(tmp_path: Path) -> None:
    client, board_id = _client_with_board(tmp_path)
    res = client.post(
        f"/boards/{board_id}/notes",
        json={"kind": "user_note", "content": "my note"},
    )
    assert res.status_code == 201
    note_id = res.json()["id"]
    listed = client.get(f"/boards/{board_id}/notes").json()
    assert [n["id"] for n in listed] == [note_id]
    assert client.delete(f"/boards/{board_id}/notes/{note_id}").status_code == 204
    assert client.get(f"/boards/{board_id}/notes").json() == []


def test_empty_content_and_engine_kinds_rejected(tmp_path: Path) -> None:
    client, board_id = _client_with_board(tmp_path)
    assert (
        client.post(
            f"/boards/{board_id}/notes", json={"kind": "user_note", "content": "  "}
        ).status_code
        == 400
    )
    # the engine-era kinds are no longer creatable (422 = schema-level rejection)
    for kind in ("pinned_fact", "ai_distilled"):
        assert (
            client.post(
                f"/boards/{board_id}/notes", json={"kind": kind, "content": "x"}
            ).status_code
            == 422
        )


def test_note_cannot_be_deleted_through_the_wrong_board(tmp_path: Path) -> None:
    client, board_id = _client_with_board(tmp_path)
    other = client.post("/boards", json={"name": "Other"}).json()["id"]
    note_id = client.post(
        f"/boards/{board_id}/notes", json={"kind": "user_note", "content": "mine"}
    ).json()["id"]
    assert client.delete(f"/boards/{other}/notes/{note_id}").status_code == 404
    assert [n["id"] for n in client.get(f"/boards/{board_id}/notes").json()] == [note_id]


def test_unknown_board_and_note_are_404(tmp_path: Path) -> None:
    client, board_id = _client_with_board(tmp_path)
    assert client.get("/boards/nope/notes").status_code == 404
    assert client.delete(f"/boards/{board_id}/notes/nope").status_code == 404


def test_note_carries_a_title_and_both_languages(tmp_path: Path) -> None:
    client, board_id = _client_with_board(tmp_path)
    created = client.post(
        f"/boards/{board_id}/notes",
        json={
            "kind": "user_note",
            "title": "私募信贷的重定价还没走完",
            "content": "利差在二季度全线走阔。",
            "title_zh": "私募信贷的重定价还没走完",
            "title_en": "Private-credit repricing is not done",
            "content_zh": "利差在二季度全线走阔。",
            "content_en": "Spreads widened through the second quarter.",
        },
    )
    assert created.status_code == 201
    note = created.json()
    assert note["title"] == "私募信贷的重定价还没走完"
    assert note["title_en"] == "Private-credit repricing is not done"
    assert note["content_en"] == "Spreads widened through the second quarter."
    # a note saved without them still reads: the authored text is the fallback
    plain = client.post(
        f"/boards/{board_id}/notes", json={"kind": "user_note", "content": "plain"}
    ).json()
    assert plain["title"] is None and plain["content_zh"] is None


def test_edit_writes_the_language_the_user_typed_in(tmp_path: Path) -> None:
    client, board_id = _client_with_board(tmp_path)
    note_id = client.post(
        f"/boards/{board_id}/notes",
        json={
            "kind": "user_note",
            "title": "旧标题",
            "content": "body",
            "title_zh": "旧标题",
            "title_en": "Old title",
        },
    ).json()["id"]

    renamed = client.patch(
        f"/boards/{board_id}/notes/{note_id}",
        json={"title": "A sharper title", "content": "A fuller body.", "locale": "en"},
    )
    assert renamed.status_code == 200
    body = renamed.json()
    assert body["title"] == "A sharper title"
    assert body["title_en"] == "A sharper title"
    assert body["content_en"] == "A fuller body."
    assert body["title_zh"] == "旧标题"  # the other language is left alone

    assert (
        client.patch(f"/boards/{board_id}/notes/{note_id}", json={"title": "   "}).status_code
        == 400
    )
    # a note can only be renamed through its own board
    other = client.post("/boards", json={"name": "Other"}).json()["id"]
    assert client.patch(f"/boards/{other}/notes/{note_id}", json={"title": "x"}).status_code == 404


def test_localize_stores_the_other_language_on_request(tmp_path: Path) -> None:
    """A note saved before the bilingual copies existed only follows the language
    switch once the user asks for it — one call, stored, never on a page open."""
    from app.clients.mock import MockLLMClient

    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    board = create_board(conn, "Finance")
    note = create_note(conn, board.id, "user_note", "利差在二季度全线走阔。")
    conn.close()

    llm = MockLLMClient(
        [{"title": "Spreads widened in Q2", "content": "Spreads widened through the quarter."}]
    )
    app = create_app()
    app.dependency_overrides[get_db] = _db_override(db)
    app.dependency_overrides[get_llm] = lambda: llm
    client = TestClient(app)

    res = client.post(f"/boards/{board.id}/notes/{note.id}/localize", params={"locale": "en"})
    assert res.status_code == 200
    body = res.json()
    assert body["content_en"] == "Spreads widened through the quarter."
    assert body["title_en"] == "Spreads widened in Q2"
    # the authored text and the other language are untouched
    assert body["content"] == "利差在二季度全线走阔。"
    assert body["content_zh"] is None
    assert len(llm.calls) == 1
