"""M13.2 — saved_check notes + the Knowledge search surface (GET /knowledge/search).

Covers: saving a negotiated check-note through the existing notes API (no citation
requirement — the underlying verify result is NOT in the fact layer), the keyword
search over saved notes (deterministic, ML-free), and the combined search envelope
that keeps verified facts and user-saved content in separate labeled lists.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi.testclient import TestClient

from app.clients.mock import MockLLMClient
from app.db.engine import init_db
from app.db.knowledge_store import create_note, search_saved_notes
from app.main import create_app, get_db, get_llm

BOARD = "b_economy"  # preset topic board (M12.1) — exists in every fresh DB


def _db_override(db_path: str) -> Callable[[], Iterator[sqlite3.Connection]]:
    def _get_db() -> Iterator[sqlite3.Connection]:
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    return _get_db


def _client(db_path: str, llm: MockLLMClient | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = _db_override(db_path)
    # an EMPTY mock-backed index: fact search legitimately returns [] — this suite
    # is about the saved-notes side; the fact side has its own memory-query tests
    # M13.5: search synthesizes an answer over hits — an exhausted mock raises and
    # the endpoint degrades to answer=None, so hit-focused tests stay unchanged
    app.dependency_overrides[get_llm] = lambda: llm if llm is not None else MockLLMClient([])
    return TestClient(app)


def test_saved_check_note_saves_without_citations(tmp_path: Path) -> None:
    """The save button's exact call: a saved_check note with NO citations — the
    verify result it came from is not in the fact layer, so nothing can resolve."""
    db = str(tmp_path / "daily.db")
    init_db(db).close()
    res = _client(db).post(
        f"/boards/{BOARD}/notes",
        json={"kind": "saved_check", "content": "Fed approved the merger (federalreserve.gov)."},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["kind"] == "saved_check"
    assert body["citations"] == []
    # user-authored: never synthesized, never a regenerable cache
    assert body["is_synthesized"] is False and body["regenerable"] is False


def test_knowledge_search_finds_saved_notes_separately_labeled(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    create_note(
        conn,
        BOARD,
        "saved_check",
        "The Fed approved the merger application (federalreserve.gov, checked 2026-07-06).",
    )
    # M16.2 review: the user's ordinary notes are searchable too (FR-15) …
    create_note(conn, BOARD, "user_note", "merger follow-up: watch the July filing")
    # … but a regenerable AI cache and a verification-derived pinned fact are NOT
    # (ai_distilled = not user content; pinned_fact = dormant with the fact layer)
    # ai_distilled is written by the distill pipeline, not create_note — raw insert
    conn.execute(
        "INSERT INTO knowledge_notes (id, board_id, kind, content, citations_json, "
        "is_synthesized, regenerable, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            "n_ai",
            BOARD,
            "ai_distilled",
            "AI cache line about the merger",
            '["cl_x"]',
            1,
            1,
            "2026-07-08T00:00:00+00:00",
        ),
    )
    conn.commit()
    # a legacy pinned_fact row (engine era) may still exist in an old DB — it
    # stays out of every layer; raw insert since the kind is no longer creatable
    conn.execute(
        "INSERT INTO knowledge_notes (id, board_id, kind, content, citations_json, "
        "is_synthesized, regenerable, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            "n_pin",
            BOARD,
            "pinned_fact",
            "Pinned fact text about the merger",
            "[]",
            0,
            0,
            "2026-07-08T00:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()

    res = _client(db).get("/knowledge/search", params={"q": "what about the Fed merger?"})
    assert res.status_code == 200
    body = res.json()
    # facts stay dormant; saved = BOTH kinds of the user's own content, labeled
    assert set(body) == {"saved", "items"}  # two layers only (engine removed)
    assert sorted(n["kind"] for n in body["saved"]) == ["saved_check", "user_note"]
    assert all("merger" in n["content"] for n in body["saved"])
    assert not any(n["kind"] in ("ai_distilled", "pinned_fact") for n in body["saved"])


def test_saved_note_search_is_token_ranked(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    create_note(conn, BOARD, "saved_check", "SEC adopted new market-structure rules.")
    create_note(conn, BOARD, "saved_check", "SEC IPO statistics for Q2 set a record.")
    # both hit "sec"; the second also hits "ipo" + "statistics" → ranked first
    hits = search_saved_notes(conn, "SEC IPO statistics")
    assert [n.content for n in hits][0] == "SEC IPO statistics for Q2 set a record."
    assert len(hits) == 2
    # no token overlap → no hits; stopword-length tokens are ignored
    assert search_saved_notes(conn, "quarterly earnings guidance") == []
    assert search_saved_notes(conn, "a of to") == []
    conn.close()


def test_saved_note_search_is_cjk_aware(tmp_path: Path) -> None:
    """M13.2 review blocker: the operator asks Knowledge in Chinese too — zh has no
    word spaces, so the keyword layer must match on CJK bigrams, not \\w+ splits."""
    conn = init_db(str(tmp_path / "daily.db"))
    create_note(conn, BOARD, "saved_check", "美联储批准并购申请。")
    # M16.2 review: a zh user_note is the user's own content — searchable too
    create_note(conn, BOARD, "user_note", "并购相关的自由笔记")

    # a short zh query hits BOTH of the user's notes (bigram 并购) …
    assert sorted(n.content for n in search_saved_notes(conn, "并购")) == [
        "并购相关的自由笔记",
        "美联储批准并购申请。",
    ]
    # … and a natural-language zh question ranks the two-bigram hit (并购 + 批准)
    # above the single-bigram user note
    ranked = [n.content for n in search_saved_notes(conn, "并购批准了吗")]
    assert ranked[0] == "美联储批准并购申请。"
    # mixed-language queries work: the en token and the zh bigram both count
    # (both notes tie on the 并购 bigram — order is a recency tie-break, not asserted)
    assert sorted(n.content for n in search_saved_notes(conn, "Fed 并购 update")) == [
        "并购相关的自由笔记",
        "美联储批准并购申请。",
    ]
    # zero-overlap zh queries still miss honestly
    assert search_saved_notes(conn, "利率决议") == []
    conn.close()


def test_knowledge_search_rejects_empty_query(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    init_db(db).close()
    assert _client(db).get("/knowledge/search", params={"q": "  "}).status_code == 400


# --- M13.5 → M16.2: the answer synthesis is on-demand; search is LLM-free ---------


def test_answer_synthesis_answers_over_notes_and_items_labeled_apart() -> None:
    """Owner 2026-07-19 ("太保守了"): the prompt ANSWERS the question — analysis
    and labeled inference welcome, never a bare 证据不足 refusal — grounded on
    BOTH layers: the user's saved notes AND tracked-item summaries (in the
    question's language). Honesty survives: no fabricated specifics, no buy/sell
    instructions."""
    from datetime import UTC, datetime

    from app.knowledge.answer import answer_from_hits
    from app.schemas.models import ItemEnrichment, KnowledgeNote, TrackedItemCard

    now = datetime(2026, 7, 6, tzinfo=UTC)
    note = KnowledgeNote(
        id="n1",
        board_id=BOARD,
        kind="saved_check",
        content="Fed approved the merger (federalreserve.gov).",
        citations=[],
        is_synthesized=False,
        regenerable=False,
        created_at=now,
    )
    item = TrackedItemCard(
        id="ti1",
        board_id=BOARD,
        url="https://example.com/fed",
        title="Fed statement",
        domain="example.com",
        tier=None,
        published=None,
        first_seen=now,
        status="fetched",
        enrichment=ItemEnrichment(
            summary_zh="来源称合并获批。", summary_en="The source says the merger was approved."
        ),
    )
    llm = MockLLMClient([{"answer": "The merger was approved; based on your note and the item."}])
    out = answer_from_hits("what did the Fed do?", [note], [item], llm=llm)
    assert out == "The merger was approved; based on your note and the item."
    call = llm.calls[0]
    assert call["escalate"] is False
    assert "User's saved note 1: Fed approved the merger" in call["user"]
    # the tracked item grounds the answer too — en question → en summary line
    assert "Tracked item 1: Fed statement (example.com)" in call["user"]
    assert "the merger was approved" in call["user"]
    assert "来源称合并获批" not in call["user"]
    assert "what did the Fed do?" in call["user"]
    # answer-first posture with honest limits
    assert "Genuinely ANSWER" in call["system"]
    assert "Never refuse to analyze" in call["system"]
    assert "never" in call["system"] and "fabricate specifics" in call["system"]
    assert "buy/sell" in call["system"]

    # a zh question flips the item summary to the zh line
    zh_llm = MockLLMClient([{"answer": "合并获批。"}])
    assert answer_from_hits("美联储做了什么?", [note], [item], llm=zh_llm) == "合并获批。"
    assert "来源称合并获批" in zh_llm.calls[0]["user"]

    # degradation: failure / wrong shape / blank / rambling → None, never raises
    assert answer_from_hits("q", [note], [], llm=MockLLMClient([])) is None
    assert answer_from_hits("q", [note], [], llm=MockLLMClient([{"reply": "x"}])) is None
    assert answer_from_hits("q", [note], [], llm=MockLLMClient([{"answer": "  "}])) is None
    assert answer_from_hits("q", [note], [], llm=MockLLMClient([{"answer": "x" * 4000}])) is None


def test_search_never_calls_llm_and_returns_dormant_fields_empty(tmp_path: Path) -> None:
    """M16.2 red line: GET /knowledge/search is deterministic SQLite only — even
    with matching notes AND tracked items it spends zero tokens, and the dormant
    fields come back empty (facts=[], answer=None)."""
    from datetime import UTC, datetime

    from app.db.tracked_item_store import upsert_discovered
    from app.tracking.feed import FeedItem

    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    create_note(conn, BOARD, "saved_check", "Fed approved the merger (federalreserve.gov).")
    upsert_discovered(
        conn,
        subscription_id="sub1",
        board_id=BOARD,
        item=FeedItem(
            guid=None,
            url="https://example.com/fed-merger",
            title="Fed merger statement",
            summary=None,
            published=None,
        ),
        now=datetime(2026, 7, 8, tzinfo=UTC),
    )
    conn.commit()
    conn.close()

    quiet = MockLLMClient([])  # would raise if anything called it
    body = _client(db, quiet).get("/knowledge/search", params={"q": "fed merger"}).json()
    assert quiet.calls == []
    assert set(body) == {"saved", "items"}  # two layers only (engine removed)
    assert len(body["saved"]) == 1
    assert [i["title"] for i in body["items"]] == ["Fed merger statement"]


def test_answer_endpoint_grounds_on_notes_and_items_not_display_layers(tmp_path: Path) -> None:
    """POST /knowledge/answer: one flash call grounded in the matching saved notes
    AND tracked items (2026-07-19); display-only distilled cache lines still never
    reach the prompt."""
    from datetime import UTC, datetime

    from app.db.tracked_item_store import upsert_discovered
    from app.tracking.feed import FeedItem

    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    create_note(conn, BOARD, "saved_check", "Fed approved the merger (federalreserve.gov).")
    upsert_discovered(
        conn,
        subscription_id="sub1",
        board_id=BOARD,
        item=FeedItem(
            guid=None,
            url="https://example.com/fed-merger",
            title="UNVERIFIED item about the fed merger",
            summary=None,
            published=None,
        ),
        now=datetime(2026, 7, 8, tzinfo=UTC),
    )
    conn.commit()
    conn.close()

    # M16.2 review: an ordinary user_note matching the query grounds the answer too
    conn = init_db(db)
    create_note(conn, BOARD, "user_note", "my own merger note: watch the July filing")
    # M16.7: a distilled cache note matching the query is DISPLAY-ONLY — it must
    # never ground the answer (derived text answering as the user's own words)
    conn.execute(
        "INSERT INTO knowledge_notes (id, board_id, kind, content, citations_json, "
        "is_synthesized, regenerable, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            "n_ai2",
            BOARD,
            "ai_distilled",
            "DISTILLED-CACHE line about the merger",
            '["cl_x"]',
            1,
            1,
            "2026-07-08T00:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()

    llm = MockLLMClient([{"answer": "Per your saved note, the merger was approved."}])
    res = _client(db, llm).post("/knowledge/answer", json={"q": "fed merger"})
    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "Per your saved note, the merger was approved."
    assert body["based_on"] == 3  # 2 notes + 1 tracked item
    assert len(llm.calls) == 1
    assert "Fed approved the merger" in llm.calls[0]["user"]
    assert "my own merger note: watch the July filing" in llm.calls[0]["user"]
    # the tracked item grounds the answer too (2026-07-19)
    assert "UNVERIFIED item about the fed merger" in llm.calls[0]["user"]
    # …but the distilled display layer still never does (M16.7)
    assert "DISTILLED-CACHE" not in llm.calls[0]["user"]


def test_answer_endpoint_zero_hits_spends_nothing(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    init_db(db).close()
    quiet = MockLLMClient([])  # would raise if called
    res = _client(db, quiet).post("/knowledge/answer", json={"q": "unrelated topic"})
    assert res.status_code == 200
    assert res.json() == {"answer": None, "based_on": 0}
    assert quiet.calls == []


def test_answer_endpoint_failure_is_a_typed_502(tmp_path: Path) -> None:
    """The user explicitly asked — an LLM failure surfaces as a retryable 502,
    never a silent null (that would be indistinguishable from "no notes")."""
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    create_note(conn, BOARD, "saved_check", "Fed approved the merger.")
    conn.close()
    # exhausted mock raises inside answer_from_hits → degraded to None → 502
    res = _client(db).post("/knowledge/answer", json={"q": "merger"})
    assert res.status_code == 502
    assert "try again" in res.json()["detail"]


def test_answer_endpoint_rejects_empty_question(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    init_db(db).close()
    assert _client(db).post("/knowledge/answer", json={"q": "  "}).status_code == 400
