"""M16.5 — the tracked-item discussion: `POST /tracked-items/{id}/discuss`.

Grounded ONLY in the item's persisted material (stored excerpt + bilingual
enrichment + card metadata). The dormant fact layer, scores, and OTHER items
never enter the prompt; the discussion is READ-ONLY — a chat writes nothing.
Failures are typed: 404 unknown item, 400 no stored text (fetch first), 502 LLM."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.engine import init_db
from app.db.tracked_item_store import tracked_item_card_by_id, upsert_discovered
from app.discuss import DiscussError, discuss_tracked_item
from app.main import create_app, get_db, get_llm
from app.schemas.models import DiscussMessage, ItemEnrichment
from app.tracking.feed import FeedItem

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)

_SEC_EXCERPT = "The Commission announced its rulemaking enters a comment period."
_POD_EXCERPT = "UNIQUE-POD-TRANSCRIPT: markets moved on central bank remarks."


class _RecordingLLM:
    """Returns a canned source-toned reply and records every prompt, so the
    grounding tests can assert what the model was — and was NOT — shown."""

    def __init__(self, reply: str = "来源称:规则进入评议期。") -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, *, system: str, user: str, escalate: bool = False) -> dict[str, object]:
        assert escalate is False  # flash-only, never escalated (NFR-7 exc. (4))
        self.calls.append((system, user))
        return {"reply": self.reply}


class _BoomLLM:
    def complete_json(self, **_: object) -> dict[str, object]:
        raise RuntimeError("llm down")


def _discover(
    conn: sqlite3.Connection,
    url: str,
    *,
    title: str,
    sub_id: str = "sub1",
    excerpt: str | None = None,
    enrichment: ItemEnrichment | None = None,
) -> str:
    upsert_discovered(
        conn,
        subscription_id=sub_id,
        board_id="b_economy",
        item=FeedItem(guid=None, url=url, title=title, summary=None, published=None),
        now=NOW,
        module_id=None,
    )
    row = conn.execute("SELECT id FROM tracked_items WHERE url = ?", (url,)).fetchone()
    item_id = str(row["id"])
    if excerpt is not None:
        conn.execute(
            "UPDATE tracked_items SET content_excerpt = ?, status = 'fetched' WHERE id = ?",
            (excerpt, item_id),
        )
    if enrichment is not None:
        conn.execute(
            "UPDATE tracked_items SET enrichment = ? WHERE id = ?",
            (json.dumps(enrichment.model_dump(), ensure_ascii=False), item_id),
        )
    conn.commit()
    return item_id


def _enrichment() -> ItemEnrichment:
    return ItemEnrichment(
        summary_zh="来源称规则进入评议期。",
        summary_en="The source says the rules enter a comment period.",
        why_zh="与市场结构监管相关。",
        why_en="Relevant to market-structure regulation.",
        entities=["SEC"],
        tags=["policy"],
        limitations_zh="仅基于节选。",
        limitations_en="Based on an excerpt only.",
    )


def _db_override(db_path: str) -> Callable[[], Iterator[sqlite3.Connection]]:
    def _get_db() -> Iterator[sqlite3.Connection]:
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    return _get_db


def _client(db_path: str, llm: object) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = _db_override(db_path)
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app)


def _ask(question: str) -> dict[str, object]:
    return {"messages": [{"role": "user", "content": question}]}


# --- grounding: the prompt holds THIS item's material and nothing else --------


def test_discuss_grounds_only_in_this_items_persisted_material(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    sec = _discover(
        conn,
        "https://www.sec.gov/news/item-1",
        title="SEC adopts rules",
        excerpt=_SEC_EXCERPT,
        enrichment=_enrichment(),
    )
    _discover(
        conn,
        "https://pod.example/ep-214",
        title="UNIQUE-POD-TITLE episode 214",
        sub_id="sub2",
        excerpt=_POD_EXCERPT,
    )
    conn.close()

    llm = _RecordingLLM()
    res = _client(db, llm).post(f"/tracked-items/{sec}/discuss", json=_ask("评议期多久?"))
    assert res.status_code == 200
    assert res.json() == {"reply": "来源称:规则进入评议期。"}

    assert len(llm.calls) == 1
    system, user = llm.calls[0]
    # the item's OWN material is all there: metadata, enrichment, excerpt, question
    assert "SEC adopts rules" in user and "sec.gov" in user
    assert _SEC_EXCERPT in user
    assert "来源称规则进入评议期。" in user  # bilingual enrichment rides along
    assert "评议期多久?" in user
    # nothing from any OTHER item ever enters the prompt
    assert "UNIQUE-POD" not in user
    # the dormant verification vocabulary never enters either side of the prompt
    for banned in ("credibility", "verdict", "stance", "/100"):
        assert banned not in system.lower() and banned not in user.lower()
    # 2026-07-13 (owner): the assistant ANSWERS with the source as anchor —
    # analysis welcome, fabrication banned
    assert "Genuinely ANSWER" in system and "never fabricate" in system
    assert "Never refuse to analyze" in system


def test_discuss_carries_the_whole_conversation(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    sec = _discover(
        conn, "https://www.sec.gov/news/item-1", title="SEC adopts rules", excerpt=_SEC_EXCERPT
    )
    conn.close()

    llm = _RecordingLLM()
    body = {
        "messages": [
            {"role": "user", "content": "评议期多久?"},
            {"role": "assistant", "content": "来源称进入评议期,未给出时长。"},
            {"role": "user", "content": "来源提到生效日期吗?"},
        ]
    }
    assert _client(db, llm).post(f"/tracked-items/{sec}/discuss", json=body).status_code == 200
    _, user = llm.calls[0]
    assert "user: 评议期多久?" in user and "assistant: 来源称进入评议期" in user


# --- typed failures ------------------------------------------------------------


def test_discuss_endpoint_typed_errors(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    ready = _discover(
        conn, "https://www.sec.gov/news/item-1", title="SEC adopts rules", excerpt=_SEC_EXCERPT
    )
    bare = _discover(conn, "https://pod.example/ep-214", title="No text yet", sub_id="sub2")
    conn.close()

    client = _client(db, _RecordingLLM())
    assert client.post("/tracked-items/nope/discuss", json=_ask("hi")).status_code == 404
    # malformed conversations: empty, or not ending on a non-empty user turn
    assert client.post(f"/tracked-items/{ready}/discuss", json={"messages": []}).status_code == 400
    res = client.post(
        f"/tracked-items/{ready}/discuss",
        json={"messages": [{"role": "assistant", "content": "hello"}]},
    )
    assert res.status_code == 400
    # no stored text → typed 400 pointing at fetch-&-summarize, never a silent guess
    res = client.post(f"/tracked-items/{bare}/discuss", json=_ask("hi"))
    assert res.status_code == 400
    assert "fetch" in res.json()["detail"]

    # an LLM failure is a loud 502 — the user asked, we never fake a reply
    res = _client(db, _BoomLLM()).post(f"/tracked-items/{ready}/discuss", json=_ask("hi"))
    assert res.status_code == 502


def test_discuss_rejects_an_unusable_model_reply(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    sec = _discover(
        conn, "https://www.sec.gov/news/item-1", title="SEC adopts rules", excerpt=_SEC_EXCERPT
    )
    card = tracked_item_card_by_id(conn, sec)
    assert card is not None
    conn.close()

    try:
        discuss_tracked_item(
            card,
            _SEC_EXCERPT,
            [DiscussMessage(role="user", content="hi")],
            llm=_RecordingLLM(reply="  "),
        )
        raise AssertionError("expected DiscussError")
    except DiscussError as exc:
        assert "no usable reply" in str(exc)


# --- READ-ONLY: a discussion never writes anything -----------------------------


def test_discuss_is_read_only(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    sec = _discover(
        conn,
        "https://www.sec.gov/news/item-1",
        title="SEC adopts rules",
        excerpt=_SEC_EXCERPT,
        enrichment=_enrichment(),
    )
    before = dict(conn.execute("SELECT * FROM tracked_items WHERE id = ?", (sec,)).fetchone())
    conn.close()

    assert (
        _client(db, _RecordingLLM())
        .post(f"/tracked-items/{sec}/discuss", json=_ask("评议期多久?"))
        .status_code
        == 200
    )

    conn = init_db(db)
    after = dict(conn.execute("SELECT * FROM tracked_items WHERE id = ?", (sec,)).fetchone())
    assert after == before  # the row is untouched
    for table in ("knowledge_notes", "memory_items"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    conn.close()
