"""Persisted knowledge Q&A chats (owner 2026-07-24): list / open / continue /
delete, with the answer call seeing the earlier turns. Offline (NFR-3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.db.engine import init_db
from app.main import create_app, get_db, get_llm


class _RecordingLLM:
    """Returns a canned answer; records prompts so history-passing is provable."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def complete_json(self, *, system: str, user: str, escalate: bool = False) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user})
        return {"answer": f"回答 {len(self.calls)}"}


def _client(db_path: str, llm: _RecordingLLM) -> TestClient:
    app = create_app()

    def _get_db() -> Iterator[sqlite3.Connection]:
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app)


def _seed_note(db_path: str) -> None:
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO knowledge_notes (id, board_id, kind, content, citations_json,"
        " is_synthesized, regenerable, created_at) VALUES"
        " ('n1', 'b_economy', 'user_note', '美联储按兵不动。', '[]', 0, 0,"
        " '2026-07-20T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()


def test_chat_create_open_continue_and_list(tmp_path: Path) -> None:
    db_path = str(tmp_path / "daily.db")
    _seed_note(db_path)
    llm = _RecordingLLM()
    client = _client(db_path, llm)

    # create: first Q&A becomes a chat titled after the question
    created = client.post("/knowledge/chats", json={"q": "美联储最近做了什么?"}).json()
    assert created["title"] == "美联储最近做了什么?"
    assert [m["role"] for m in created["messages"]] == ["user", "assistant"]
    assert created["messages"][1]["content"] == "回答 1"
    assert created["based_on"] == 1  # the seeded note grounded it

    # list shows it; open returns the full conversation
    chats = client.get("/knowledge/chats").json()
    assert [c["message_count"] for c in chats] == [2]
    opened = client.get(f"/knowledge/chats/{created['id']}").json()
    assert opened["messages"] == created["messages"]
    assert opened["based_on"] is None  # transient field: only set on asks

    # continue: the answer call sees the earlier turns
    updated = client.post(
        f"/knowledge/chats/{created['id']}/messages", json={"q": "那对美股意味着什么?"}
    ).json()
    assert [m["role"] for m in updated["messages"]] == ["user", "assistant"] * 2
    assert "Conversation so far:" in llm.calls[1]["user"]
    assert "美联储最近做了什么?" in llm.calls[1]["user"]  # first turn included
    # the corpus precedes the conversation (stable prompt prefix for caching)
    assert llm.calls[1]["user"].index("美联储按兵不动") < llm.calls[1]["user"].index(
        "Conversation so far:"
    )

    # delete removes the chat but never the knowledge it talked about
    assert client.delete(f"/knowledge/chats/{created['id']}").status_code == 204
    assert client.get("/knowledge/chats").json() == []
    conn = init_db(db_path)
    assert conn.execute("SELECT COUNT(*) FROM knowledge_notes").fetchone()[0] == 1
    conn.close()


def test_chat_asks_are_typed_on_bad_input(tmp_path: Path) -> None:
    db_path = str(tmp_path / "daily.db")
    llm = _RecordingLLM()
    client = _client(db_path, llm)

    # empty knowledge base → typed 400, no LLM call, no husk chat
    resp = client.post("/knowledge/chats", json={"q": "有什么新闻?"})
    assert resp.status_code == 400 and llm.calls == []
    assert client.get("/knowledge/chats").json() == []

    _seed_note(db_path)
    assert client.post("/knowledge/chats", json={"q": "  "}).status_code == 400
    assert client.post("/knowledge/chats/nope/messages", json={"q": "hi"}).status_code == 404
    assert client.get("/knowledge/chats/nope").status_code == 404
    assert client.delete("/knowledge/chats/nope").status_code == 404


def test_failed_continue_saves_nothing(tmp_path: Path) -> None:
    db_path = str(tmp_path / "daily.db")
    _seed_note(db_path)

    class _BoomLLM:
        def complete_json(self, **_: object) -> dict[str, Any]:
            raise RuntimeError("LLM down")

    good = _RecordingLLM()
    client = _client(db_path, good)
    chat_id = client.post("/knowledge/chats", json={"q": "问题一"}).json()["id"]

    boom_client = _client(db_path, _BoomLLM())  # type: ignore[arg-type]
    resp = boom_client.post(f"/knowledge/chats/{chat_id}/messages", json={"q": "问题二"})
    assert resp.status_code == 502
    # the failed turn left no trace — the chat still has exactly the first Q&A
    assert client.get(f"/knowledge/chats/{chat_id}").json()["messages"].__len__() == 2
