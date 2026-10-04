"""M7.3 — RSS autodiscovery (SSOT §6.1 step 2).

Finds feeds a page advertises via <link rel="alternate" type="…rss/atom…">. Scope:
HTML parsing only — no network (M7.7), no platform rules (M7.4), no homepage-diff
(M7.5). Non-feed <link>s are ignored; relative hrefs resolve against base."""

from __future__ import annotations

from app.tracking.discover import discover_feeds
from tests.fixtures_loader import fixture_path


def _html() -> bytes:
    return fixture_path("feeds/autodiscover.html").read_bytes()


def test_discovers_feed_links_and_ignores_non_feeds() -> None:
    feeds = discover_feeds(_html(), base_url="https://blog.example.com/")
    assert feeds == [
        "https://blog.example.com/feed.xml",  # relative RSS resolved against base
        "https://blog.example.com/atom.xml",  # absolute Atom unchanged
        "https://blog.example.com/comments/feed.xml",
    ]
    # the stylesheet, icon, and JSON-feed <link>s are not RSS/Atom → excluded
    assert all("feed.json" not in f for f in feeds)


def test_no_base_url_keeps_relative_href() -> None:
    feeds = discover_feeds(b'<link rel="alternate" type="application/rss+xml" href="/feed.xml">')
    assert feeds == ["/feed.xml"]


def test_base_href_tag_is_honored() -> None:
    html = (
        '<head><base href="https://cdn.example.com/blog/">'
        '<link rel="alternate" type="application/atom+xml" href="atom.xml"></head>'
    )
    assert discover_feeds(html, base_url="https://example.com/") == [
        "https://cdn.example.com/blog/atom.xml"
    ]


def test_rel_with_multiple_tokens_matches() -> None:
    html = '<link rel="alternate home" type="application/rss+xml" href="https://x.example/f.xml">'
    assert discover_feeds(html) == ["https://x.example/f.xml"]


def test_rdf_feed_type_is_discovered() -> None:
    html = '<link rel="alternate" type="application/rdf+xml" href="https://x.example/rdf.xml">'
    assert discover_feeds(html) == ["https://x.example/rdf.xml"]


def test_duplicate_links_are_deduped_in_order() -> None:
    html = (
        '<link rel="alternate" type="application/rss+xml" href="https://x.example/f.xml">'
        '<link rel="alternate" type="application/rss+xml" href="https://x.example/f.xml">'
    )
    assert discover_feeds(html) == ["https://x.example/f.xml"]


def test_no_feeds_returns_empty() -> None:
    assert discover_feeds(b"<html><head><title>no feeds</title></head></html>") == []
