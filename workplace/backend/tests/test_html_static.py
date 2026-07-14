"""M1A.4 — HTML static extraction: clean page → raw_text(static_html); empty/
too-short → fallback marker; the httpx client honours the X0.8 fetch policy; all
fetches are cassette-replayed (offline, NFR-3)."""

from __future__ import annotations

from app.ingestion.html_static import (
    build_client,
    extract_main_text,
    fetch_html,
    ingest_html_static,
)
from tests import fixtures_loader as fx
from tests.http_cassette import replay

# --- pure extraction --------------------------------------------------------


def test_extract_clean_article_yields_main_text() -> None:
    text = extract_main_text(fx.load_text("html/static_article.html"))
    assert text is not None
    assert "$30.8B" in text


def test_extract_empty_body_is_too_short() -> None:
    # nav/footer boilerplate only → below the main-text threshold → None
    assert extract_main_text(fx.load_text("html/empty_body.html")) is None


# --- client honours the X0.8 fetch policy -----------------------------------


def test_build_client_uses_fetch_policy() -> None:
    with build_client() as client:
        assert client._trust_env is False  # no env proxy (§2.2)
        assert not client.cookies  # no cookies
        assert client.timeout.connect is not None  # a timeout exists
        assert client.follow_redirects is True


# --- fetch + end-to-end via cassette (offline) ------------------------------


def test_fetch_html_via_cassette() -> None:
    with replay("html_article.yaml"), build_client() as client:
        body, content_type = fetch_html("https://news.example.com/nvda", client=client)
    assert "$30.8B" in body
    assert "text/html" in content_type


def test_ingest_clean_page_produces_static_html_source() -> None:
    with replay("html_article.yaml"), build_client() as client:
        result = ingest_html_static("https://news.example.com/nvda", client=client)
    assert result.empty is False
    assert result.source is not None
    assert result.source.extraction_method == "static_html"
    assert result.source.type == "webpage"
    assert result.source.url == "https://news.example.com/nvda"
    assert result.source.domain == "news.example.com"
    assert "$30.8B" in result.source.raw_text


def test_ingest_empty_page_signals_fallback() -> None:
    with replay("html_empty.yaml"), build_client() as client:
        result = ingest_html_static("https://news.example.com/empty", client=client)
    assert result.empty is True
    assert result.source is None
