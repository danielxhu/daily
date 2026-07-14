"""M7.2 — direct RSS/Atom feed parser (SSOT §6.1 step 1).

Parses recorded RSS 2.0 + Atom feeds into transient `FeedItem`s. Scope: parsing
only — no network, no dedup key (M7.6), no feed resolution (M7.3-5). Best-effort:
malformed / non-feed / DTD-bearing content raises FeedParseError; a missing field
stays None instead of dropping the item."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.tracking.feed import FeedItem, FeedParseError, parse_feed
from tests.fixtures_loader import fixture_path


def _rss() -> bytes:
    return fixture_path("feeds/rss_sample.xml").read_bytes()


def _atom() -> bytes:
    return fixture_path("feeds/atom_sample.xml").read_bytes()


def _rdf() -> bytes:
    return fixture_path("feeds/rdf_sample.xml").read_bytes()


def test_parse_rss_extracts_items() -> None:
    items = parse_feed(_rss())
    assert len(items) == 3
    first = items[0]
    assert first.guid == "sec-press-2026-101"
    assert first.url == "https://www.sec.gov/news/press-release/2026-101"
    assert first.title == "SEC Charges Investment Adviser With Misleading Disclosures"
    assert first.summary == "The SEC announced charges against an adviser over fee disclosures."
    # RFC 822 pubDate → an aware datetime
    assert first.published == datetime.fromisoformat("2026-06-09T13:30:00+00:00")


def test_rss_item_missing_optional_fields_is_kept_with_none() -> None:
    # the third item has no <guid> and no <pubDate>: best-effort keeps it
    third = parse_feed(_rss())[2]
    assert third.guid is None and third.published is None
    assert third.url == "https://www.sec.gov/news/statement/market-structure-2026"


def test_parse_atom_extracts_entries() -> None:
    items = parse_feed(_atom())
    assert len(items) == 2
    first = items[0]
    assert first.guid == "yt:video:abc123"
    # the alternate link is the canonical entry URL (not rel="self")
    assert first.url == "https://www.youtube.com/watch?v=abc123"
    assert first.title == "Markets wrap: stocks close higher"
    assert first.published == datetime.fromisoformat("2026-06-09T21:05:00+00:00")


def test_atom_alternate_link_preferred_over_self() -> None:
    second = parse_feed(_atom())[1]
    assert second.url == "https://www.youtube.com/watch?v=def456"
    # falls back to <content> when there is no <summary>, and to <updated> for the date
    assert second.summary == "What to watch ahead of the rate decision."
    assert second.published == datetime.fromisoformat("2026-06-08T12:00:00+00:00")


def test_parse_rss1_rdf_feed() -> None:
    # RSS 1.0's root is <rdf:RDF> (local name "RDF"); items live as siblings of
    # <channel> and are identified by rdf:about (there is no <guid>).
    items = parse_feed(_rdf())
    assert len(items) == 2
    first = items[0]
    assert first.title == "First RDF article"
    assert first.url == "https://example.com/articles/1"
    assert first.guid == "https://example.com/articles/1"  # from rdf:about
    # dc:date (W3CDTF / ISO 8601) parses
    assert first.published == datetime.fromisoformat("2026-06-09T08:00:00+00:00")


def test_malformed_xml_raises() -> None:
    with pytest.raises(FeedParseError):
        parse_feed(b"<rss><channel><item><title>oops")


def test_non_feed_xml_raises() -> None:
    with pytest.raises(FeedParseError):
        parse_feed(b"<html><body><p>not a feed</p></body></html>")


def test_dtd_bearing_feed_is_refused() -> None:
    # safe-XML: a DTD (where entity bombs live) is rejected before parsing
    bomb = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE rss [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>'
        b"<rss><channel><item><title>&lol2;</title></channel></rss>"
    )
    with pytest.raises(FeedParseError):
        parse_feed(bomb)


def test_accepts_str_input() -> None:
    items = parse_feed(_rss().decode("utf-8"))
    assert isinstance(items[0], FeedItem) and len(items) == 3
