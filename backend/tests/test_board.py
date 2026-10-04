"""M6.1 — Board schema + CRUD API (SSOT FR-15 / §7).

A board is a single-operator topic collection, not a user account. CRUD round-trips
through SQLite, and the scope red line holds: the schema has NO user / account /
auth / permission tables (V1 is a local single-operator app)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.board_store import create_board, delete_board, get_board, list_boards
from app.db.engine import init_db
from app.main import create_app, get_db


def _db_override(db_path: str) -> Callable[[], Iterator[sqlite3.Connection]]:
    def _get_db() -> Iterator[sqlite3.Connection]:
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    return _get_db


def _client(db_path: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = _db_override(db_path)
    return TestClient(app)


# --- store -----------------------------------------------------------------


def test_board_store_crud_roundtrip(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    board = create_board(conn, "finance")
    assert board.name == "finance" and board.id
    fetched = get_board(conn, board.id)
    assert fetched is not None and fetched.name == "finance"
    # a fresh DB carries the M12.1 preset topic boards alongside the new one
    assert board.id in [b.id for b in list_boards(conn)]
    assert delete_board(conn, board.id) is True
    assert get_board(conn, board.id) is None
    assert delete_board(conn, board.id) is False  # already gone


def test_preset_topic_boards_seeded_once(tmp_path: Path) -> None:
    # M12.1: a fresh DB has the 政治/经济/科技 preset boards (fixed ids, so the
    # static source-pack recommendations can reference them)…
    conn = init_db(str(tmp_path / "daily.db"))
    by_id = {b.id: b.name for b in list_boards(conn)}
    assert by_id["b_politics"] == "政治"
    assert by_id["b_economy"] == "经济"
    assert by_id["b_tech"] == "科技"
    # …seeded exactly once: a deleted preset stays deleted on re-migration (the
    # data migration is in the ledger, so it never resurrects user deletions)
    assert delete_board(conn, "b_politics") is True
    conn.close()
    conn = init_db(str(tmp_path / "daily.db"))
    assert "b_politics" not in [b.id for b in list_boards(conn)]


# --- API -------------------------------------------------------------------


def test_create_list_get_delete_board(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "daily.db"))
    created = client.post("/boards", json={"name": "semiconductors"})
    assert created.status_code == 201
    board_id = created.json()["id"]
    assert created.json()["name"] == "semiconductors"

    listing = client.get("/boards").json()
    # presets (M12.1) + the one just created
    assert board_id in [b["id"] for b in listing]
    assert client.get(f"/boards/{board_id}").json()["name"] == "semiconductors"

    assert client.delete(f"/boards/{board_id}").status_code == 204
    assert client.get(f"/boards/{board_id}").status_code == 404


def test_empty_name_is_400_and_unknown_board_is_404(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "daily.db"))
    assert client.post("/boards", json={"name": "   "}).status_code == 400
    assert client.get("/boards/nope").status_code == 404
    assert client.delete("/boards/nope").status_code == 404


# --- scope red line: no auth / users / accounts ----------------------------


def test_schema_has_no_user_or_account_tables(tmp_path: Path) -> None:
    # FR-15 / §2.2: V1 is a single-operator local app — boards are NOT accounts.
    conn = init_db(str(tmp_path / "daily.db"))
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    forbidden = ("user", "users", "account", "accounts", "auth", "permission", "session", "login")
    offenders = [t for t in tables if any(word in t.lower() for word in forbidden)]
    assert offenders == [], f"auth/account-like tables present: {offenders}"
