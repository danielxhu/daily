"""M15.1a — tracked items as first-class knowledge (v0.12 P0 / Stage 15 gate).

The Stage-15 review-gate red line, as tests: an item a poll discovered must stay
visible in the digest's `tracked` channel whatever the deep pipeline does —
extraction/stance/scoring all failing degrades the item, it never disappears.
Discovery writes the row; later phases only settle its own lifecycle status.
No credibility is ever fabricated for an unscored item (the card has no such
field by design)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.db.engine import init_db
from app.db.subscription_store import get_subscription
from app.db.tracked_item_store import recent_tracked_items, upsert_discovered
from app.ingestion.result import failed_from
from app.schemas.models import IngestionResult, SourceRequest
from app.tracking.digest import assemble_digest
from app.tracking.feed import FeedItem
from app.tracking.runtime import run_poll
from tests.test_tracking_runtime import (
    NOW,
    _fake_ingest,
    _KeyedLLM,
    _rss,
    _sec_subscription,
)

REAL_NOW = datetime.now(UTC)  # poll-side discovery stamps wall-clock time


def _feed_item(url: str, *, title: str | None = "An item", guid: str | None = None) -> FeedItem:
    return FeedItem(guid=guid, url=url, title=title, summary=None, published=None)


# --- store ------------------------------------------------------------------


def test_discovered_item_is_immediately_queryable_with_code_first_tier(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    upsert_discovered(
        conn,
        subscription_id="sub1",
        board_id="b1",
        item=_feed_item("https://www.sec.gov/news/item-1", title="SEC adopts rules"),
        now=REAL_NOW,
    )
    cards = recent_tracked_items(conn, since=REAL_NOW - timedelta(days=1))
    assert len(cards) == 1
    card = cards[0]
    assert card.status == "new" and card.title == "SEC adopts rules"
    assert card.domain == "sec.gov" and card.tier == "T1"  # P1 lite signal, code-first
    assert card.board_id == "b1"


def test_rediscovery_updates_the_same_row_keeping_id_and_first_seen(tmp_path: Path) -> None:
    """A deferred item is re-discovered next poll (M14.5) — same row, not a dup."""
    conn = init_db(str(tmp_path / "daily.db"))
    item = _feed_item("https://example.com/a", guid="guid-a")
    upsert_discovered(conn, subscription_id="sub1", board_id=None, item=item, now=REAL_NOW)
    first = recent_tracked_items(conn, since=REAL_NOW - timedelta(days=1))[0]
    upsert_discovered(
        conn, subscription_id="sub1", board_id=None, item=item, now=REAL_NOW + timedelta(hours=1)
    )
    cards = recent_tracked_items(conn, since=REAL_NOW - timedelta(days=1))
    assert len(cards) == 1  # keyed like seen_items — one row per item
    assert cards[0].id == first.id and cards[0].first_seen == first.first_seen


# --- the Stage-15 red line ---------------------------------------------------


class _BoomLLM:
    """Every LLM call fails — extraction, stance, scoring, enrichment, all of it."""

    def complete_json(self, *, system: str, user: str, escalate: bool = False) -> dict[str, Any]:
        raise RuntimeError("LLM down")


def test_items_stay_visible_when_every_llm_call_fails(tmp_path: Path) -> None:
    """Gate 15 red line, tracking-only poll (2026-07-10): a dead LLM costs ONLY
    the AI summary — every discovered item is still written, visible in the
    tracked channel as cleanly fetched (no misleading "processing" status, since
    extraction no longer runs at poll time), and the poll report / source health
    stay unpolluted. No fact, no score, no lie."""
    conn = init_db(str(tmp_path / "daily.db"))
    sub = _sec_subscription(conn)
    report = run_poll(
        conn,
        llm=_BoomLLM(),
        fetch=lambda _url: _rss(),
        ingest=_fake_ingest,
        now=NOW,
    )
    digest = assemble_digest(conn, now=datetime.now(UTC))
    assert len(digest.tracked) == 3  # … but every discovered item is visible
    for card in digest.tracked:
        assert card.status == "fetched"  # ingestion succeeded; only the summary failed
        assert card.degraded_reason is None  # no extraction at poll → no fake status
        assert card.enrichment is None  # honest pending state, never fabricated
        assert not hasattr(card, "credibility")  # no fabricated score, by schema
    # an LLM failure must NOT pollute the poll report or source health — the
    # fetch worked (M15.1a semantics, unchanged by the tracking-only poll)
    r = report.subscriptions[0]
    assert r.ok and r.failure_kind is None and r.error is None
    assert r.items_ok == 3 and r.items_failed == 0 and r.item_failures == []
    refreshed = get_subscription(conn, sub.id)
    assert refreshed is not None and refreshed.health == "ok"
    assert refreshed.subscription_failure_kind is None and refreshed.last_error is None


def test_mixed_real_and_deep_failures_are_accounted_separately(tmp_path: Path) -> None:
    """One article truly blocked (anti_bot) + the rest fetched but extraction-failed:
    only the REAL ingestion failure counts in the report; the deep failures degrade
    their tracked items only. Nothing vanishes."""
    calls = {"n": 0}

    def one_blocked(req: SourceRequest) -> IngestionResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return failed_from(req, "anti_bot", reason="blocked", requested_url=req.url)
        return _fake_ingest(req)

    conn = init_db(str(tmp_path / "daily.db"))
    _sec_subscription(conn)
    report = run_poll(
        conn,
        llm=_BoomLLM(),  # extraction fails for everything that fetched
        fetch=lambda _url: _rss(),
        ingest=one_blocked,
        now=NOW,
    )
    r = report.subscriptions[0]
    assert r.items_failed == 1  # only the anti_bot item
    assert [f.kind for f in r.item_failures] == ["anti_bot"]
    assert r.items_ok == 2  # fetched-but-unextracted items count as ingestion OK
    assert r.failure_kind != "items_unfetchable"  # some items fetched → not unfetchable
    cards = recent_tracked_items(conn, since=datetime.now(UTC) - timedelta(days=1))
    by_status = {c.status for c in cards}
    assert len(cards) == 3 and by_status == {"failed", "fetched"}  # all three visible


def test_ingestion_failure_keeps_the_item_visible_with_its_typed_kind(tmp_path: Path) -> None:
    def blocked(req: SourceRequest) -> IngestionResult:
        return failed_from(req, "anti_bot", reason="blocked", requested_url=req.url)

    conn = init_db(str(tmp_path / "daily.db"))
    _sec_subscription(conn)
    run_poll(
        conn,
        llm=_KeyedLLM(),
        fetch=lambda _url: _rss(),
        ingest=blocked,
        now=NOW,
    )
    cards = recent_tracked_items(conn, since=datetime.now(UTC) - timedelta(days=1))
    assert len(cards) == 3
    assert all(c.status == "failed" and c.failure_kind == "anti_bot" for c in cards)


def test_processed_items_settle_as_fetched(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    _sec_subscription(conn)
    run_poll(
        conn,
        llm=_KeyedLLM(),
        fetch=lambda _url: _rss(),
        ingest=_fake_ingest,
        now=NOW,
    )
    cards = recent_tracked_items(conn, since=datetime.now(UTC) - timedelta(days=1))
    assert len(cards) == 3
    assert all(c.status == "fetched" and c.degraded_reason is None for c in cards)


# --- M15.1: item↔fact lineage (deep-check verdicts as enrichment references) --


def test_fetched_items_get_a_poll_time_bilingual_enrichment(tmp_path: Path) -> None:
    """The raw text is only alive during the poll — each fetched item gets ONE
    flash BILINGUAL enrichment right there (NFR-7 exception (3); M16.3: zh + en in
    the same call so the locale toggle follows instantly), and its content
    excerpt is persisted for later discussion/re-enrich grounding."""
    conn = init_db(str(tmp_path / "daily.db"))
    _sec_subscription(conn)
    run_poll(
        conn,
        llm=_KeyedLLM(),
        fetch=lambda _url: _rss(),
        ingest=_fake_ingest,
        now=NOW,
    )
    cards = recent_tracked_items(conn, since=datetime.now(UTC) - timedelta(days=1))
    assert len(cards) == 3
    for c in cards:
        assert c.enrichment is not None
        assert c.enrichment.summary_zh == "来源称规则进入评议期。"
        assert c.enrichment.summary_en == "The source says the rules enter a comment period."
        assert c.enrichment.tags == ["policy"]
        assert c.content_available is True  # the excerpt landed too
        assert c.summary is None  # the deprecated single-language field stays dead


def test_enrichment_failure_leaves_pending_but_keeps_the_excerpt(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    _sec_subscription(conn)
    report = run_poll(
        conn,
        llm=_BoomLLM(),  # enrichment fails along with everything else
        fetch=lambda _url: _rss(),
        ingest=_fake_ingest,
        now=NOW,
    )
    assert report.subscriptions[0].ok
    cards = recent_tracked_items(conn, since=datetime.now(UTC) - timedelta(days=1))
    # honest pending, never a fake line …
    assert all(c.enrichment is None and c.summary is None for c in cards)
    # … but the excerpt was persisted BEFORE the LLM ran (code-only): a manual
    # re-enrich has material to work from even after a fully dead-LLM poll
    assert all(c.content_available for c in cards)


def test_knowledge_search_lists_items_apart_and_never_in_the_answer(tmp_path: Path) -> None:
    """v0.12 P0 "searchable": tracked items match by keyword in their own labeled
    list. With ONLY item hits (no facts, no saved notes) the AI answer stays None —
    exception (5) must never synthesize over unverified item content."""
    from app.clients.mock import MockLLMClient
    from app.main import create_app, get_db, get_llm

    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    upsert_discovered(
        conn,
        subscription_id="sub1",
        board_id=None,
        item=_feed_item("https://www.sec.gov/news/item-1", title="SEC market-structure rules"),
        now=REAL_NOW,
    )
    conn.close()

    from collections.abc import Iterator

    def _get_db() -> Iterator[Any]:
        c = init_db(db)
        try:
            yield c
        finally:
            c.close()

    class _NoIndex:
        def query(self, *a: Any, **k: Any) -> list[Any]:
            raise RuntimeError("semantic search unavailable")

    from fastapi.testclient import TestClient

    app = create_app()
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_llm] = lambda: MockLLMClient([])  # raises if called
    res = TestClient(app).get("/knowledge/search", params={"q": "market-structure"})
    assert res.status_code == 200
    body = res.json()
    assert body["saved"] == []
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "SEC market-structure rules"
    assert "credibility" not in body["items"][0]  # still no fabricated score


# --- M15.4: code-first duplicate/repost lite hint -----------------------------


def test_similar_count_hints_cross_domain_echo_only(tmp_path: Path) -> None:
    """Same normalized title from OTHER domains → a triage hint. Same-domain
    repeats don't count (echo, not corroboration), and the hint is pure code —
    it is never a corroboration verdict (that stays the deep path's job)."""
    conn = init_db(str(tmp_path / "daily.db"))
    for i, (url, title) in enumerate(
        [
            ("https://reuters.com/a", "Fed Holds Rates Steady"),
            ("https://apnews.com/b", "fed holds  rates   steady"),  # case/space-insensitive
            ("https://reuters.com/c", "Fed Holds Rates Steady"),  # same domain — no echo
            ("https://bbc.co.uk/d", "A completely different story"),
        ]
    ):
        upsert_discovered(
            conn,
            subscription_id=f"sub{i}",
            board_id=None,
            item=_feed_item(url, title=title),
            now=REAL_NOW,
        )
    cards = {c.url: c for c in recent_tracked_items(conn, since=REAL_NOW - timedelta(days=1))}
    assert cards["https://reuters.com/a"].similar_count == 1  # apnews echoes it
    assert cards["https://apnews.com/b"].similar_count == 1  # reuters echoes it
    assert cards["https://reuters.com/c"].similar_count == 1  # apnews (not its own domain twin)
    assert cards["https://bbc.co.uk/d"].similar_count == 0


# --- M16.3: bilingual enrichment ---------------------------------------------


def _enrichment_json() -> dict[str, object]:
    return {
        "summary_zh": "来源称美联储维持利率不变。",
        "summary_en": "The source says the Fed held rates steady.",
        "why_zh": "与利率追踪相关。",
        "why_en": "Relevant to rate tracking.",
        "entities": ["Federal Reserve"],
        "tags": ["rates", "policy"],
        "limitations_zh": "仅基于正文节选。",
        "limitations_en": "Based on an excerpt only.",
    }


def test_enrich_prompt_is_source_attributed_and_validated() -> None:
    """The single flash call: bilingual output, source-attributed wording, no
    truth/score/advice language allowed to leak; broken summaries sink the whole
    enrichment while broken OPTIONAL fields degrade individually."""
    from app.clients.mock import MockLLMClient
    from app.tracking.summarize import enrich_fetched_item

    llm = MockLLMClient([_enrichment_json()])
    out = enrich_fetched_item(
        "The Federal Reserve held its benchmark rate steady on Wednesday…",
        title="Fed holds rates",
        domain="reuters.com",
        llm=llm,
    )
    assert out is not None
    assert out.summary_zh.startswith("来源称") and "Fed held rates steady" in out.summary_en
    assert out.tags == ["rates", "policy"]
    call = llm.calls[0]
    assert call["escalate"] is False
    assert "never assert truth" in call["system"]
    assert "never give investment advice" in call["system"].lower() or (
        "investment advice" in call["system"]
    )
    assert "not translated" in call["system"]  # entities stay as written
    assert "Fed holds rates" in call["user"] and "reuters.com" in call["user"]

    # a missing/blank/oversized summary in EITHER language sinks the enrichment
    bad = dict(_enrichment_json())
    del bad["summary_en"]
    assert enrich_fetched_item("x", title=None, domain=None, llm=MockLLMClient([bad])) is None
    bad2 = dict(_enrichment_json())
    bad2["summary_zh"] = "  "
    assert enrich_fetched_item("x", title=None, domain=None, llm=MockLLMClient([bad2])) is None
    bad3 = dict(_enrichment_json())
    bad3["summary_en"] = "x" * 2000
    assert enrich_fetched_item("x", title=None, domain=None, llm=MockLLMClient([bad3])) is None
    # … but a broken optional field only drops that field
    partial = dict(_enrichment_json())
    partial["why_en"] = 123
    partial["tags"] = "not-a-list"
    got = enrich_fetched_item("x", title=None, domain=None, llm=MockLLMClient([partial]))
    assert got is not None and got.why_en is None and got.tags == []
    # total failure / empty content → None, never raises
    assert enrich_fetched_item("x", title=None, domain=None, llm=MockLLMClient([])) is None
    assert enrich_fetched_item("   ", title=None, domain=None, llm=MockLLMClient([{}])) is None


def test_search_matches_bilingual_enrichment_text(tmp_path: Path) -> None:
    """M16.3: search covers the enrichment (zh + en + tags), so an item is
    findable in either language even when its title matches neither query."""
    from app.db.tracked_item_store import search_tracked_items, set_item_enrichment
    from app.schemas.models import ItemEnrichment

    conn = init_db(str(tmp_path / "daily.db"))
    upsert_discovered(
        conn,
        subscription_id="sub1",
        board_id="b1",
        item=_feed_item("https://www.sec.gov/news/item-1", title="Untitled statement"),
        now=REAL_NOW,
    )
    set_item_enrichment(
        conn,
        subscription_id="sub1",
        item_key="https://www.sec.gov/news/item-1",
        enrichment=ItemEnrichment.model_validate(_enrichment_json()),
    )
    # zh query hits via summary_zh; en query hits via summary_en; tag hits too
    assert [c.title for c in search_tracked_items(conn, "利率")] == ["Untitled statement"]
    assert [c.title for c in search_tracked_items(conn, "rates steady")] == ["Untitled statement"]
    hit = search_tracked_items(conn, "利率")[0]
    assert hit.enrichment is not None and hit.enrichment.summary_en.endswith("steady.")
    conn.close()
