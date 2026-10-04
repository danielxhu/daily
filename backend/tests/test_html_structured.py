"""M1B.1 — HTML structured fallback (tier 2).

JSON-LD `articleBody` is a real body → `ok`; a bare og/meta description is only a
blurb → `partial` (still falls through to render, M1B.2); nothing → `empty`.
Malformed JSON-LD must degrade, not crash."""

from __future__ import annotations

from app.ingestion.html_structured import extract_structured
from tests import fixtures_loader as fx


def test_jsonld_articlebody_is_ok() -> None:
    result = extract_structured(fx.load_text("html/structured_jsonld.html"))
    assert result.status == "ok"
    assert result.text is not None and "Federal Reserve" in result.text


def test_og_description_only_is_partial() -> None:
    # a bare og:description blurb is NOT a body → partial, caller still renders
    result = extract_structured(fx.load_text("html/og_description_only.html"))
    assert result.status == "partial"
    assert result.text == "Stocks closed higher as tech led gains."


def test_no_metadata_is_empty() -> None:
    result = extract_structured(fx.load_text("html/empty_body.html"))
    assert result.status == "empty"
    assert result.text is None


def test_meta_name_description_counts_as_partial() -> None:
    html = '<html><head><meta name="description" content="A plain meta blurb."></head></html>'
    result = extract_structured(html)
    assert result.status == "partial"
    assert result.text == "A plain meta blurb."


def test_malformed_jsonld_degrades_to_meta_blurb() -> None:
    html = (
        "<html><head>"
        '<script type="application/ld+json">{ this is not valid json }</script>'
        '<meta property="og:description" content="Fallback blurb.">'
        "</head></html>"
    )
    result = extract_structured(html)
    assert result.status == "partial"  # bad JSON-LD skipped, not crashed
    assert result.text == "Fallback blurb."


def test_non_article_articlebody_is_not_ok() -> None:
    # A non-Article object carrying an articleBody key must NOT count as a body —
    # it would wrongly skip the render fallback (M1B.1 blocker).
    html = (
        "<html><head>"
        '<script type="application/ld+json">'
        '{"@type":"Product","articleBody":"this is not really an article body"}'
        "</script></head></html>"
    )
    assert extract_structured(html).status == "empty"


def test_non_article_articlebody_degrades_to_blurb_when_present() -> None:
    html = (
        "<html><head>"
        '<script type="application/ld+json">'
        '{"@type":"Product","articleBody":"product copy"}'
        "</script>"
        '<meta property="og:description" content="A product blurb.">'
        "</head></html>"
    )
    result = extract_structured(html)
    assert result.status == "partial"
    assert result.text == "A product blurb."


def test_type_as_list_with_article_member_is_ok() -> None:
    body = "Markets rallied on cooler inflation data as the index closed up over two percent today."
    html = (
        "<html><head>"
        '<script type="application/ld+json">'
        '{"@type":["CreativeWork","NewsArticle"],"articleBody":"' + body + '"}'
        "</script></head></html>"
    )
    result = extract_structured(html)
    assert result.status == "ok"
    assert result.text == body


def test_schema_org_url_type_is_ok() -> None:
    body = "The central bank signaled a pause, leaving its policy rate unchanged at the meeting."
    html = (
        "<html><head>"
        '<script type="application/ld+json">'
        '{"@type":"https://schema.org/NewsArticle","articleBody":"' + body + '"}'
        "</script></head></html>"
    )
    assert extract_structured(html).status == "ok"


def test_jsonld_articlebody_inside_graph_array() -> None:
    body = "Company X agreed to acquire Company Y for $4B in an all-cash deal announced today."
    html = (
        "<html><head>"
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@graph":'
        '[{"@type":"WebSite"},{"@type":"NewsArticle","articleBody":"' + body + '"}]}'
        "</script></head></html>"
    )
    result = extract_structured(html)
    assert result.status == "ok"
    assert result.text == body
