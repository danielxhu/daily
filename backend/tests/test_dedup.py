"""M7.6 — SeenItem set dedup (SSOT §6.2 / §6.3).

Dedup key precedence (guid → canonical URL → content hash) + set-based selection
against the seen-items store: an RSS reorder never re-emits an old item (no single
cursor), and duplicates aren't re-sent. Scope: dedup only — no scheduler (M7.7)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.db.engine import init_db
from app.db.seen_store import is_seen, mark_seen
from app.tracking.dedup import canonical_url, dedup_key, mark_items_seen, select_new_items
from app.tracking.feed import FeedItem, parse_feed
from tests.fixtures_loader import fixture_path


def _item(guid: str | None = None, url: str | None = None, title: str | None = None) -> FeedItem:
    return FeedItem(guid=guid, url=url, title=title, summary=None, published=None)


# --- dedup key precedence -------------------------------------------------


def test_key_prefers_guid_then_url_then_hash() -> None:
    assert dedup_key(_item(guid="g1", url="https://x/a")) == "g1"
    assert dedup_key(_item(url="https://x/a")) == "https://x/a"
    # no guid, no url → a stable content hash
    k = dedup_key(_item(title="Some headline"))
    assert k.startswith("sha256:")
    assert k == dedup_key(_item(title="Some headline"))  # deterministic


def test_canonical_url_strips_tracking_and_fragment() -> None:
    assert canonical_url("HTTPS://News.Example.com/a/?utm_source=tw&id=7#sec") == (
        "https://news.example.com/a?id=7"
    )
    # a bare trailing slash is normalized away (but the root path is kept)
    assert canonical_url("https://x.example/a/") == "https://x.example/a"


def test_url_keyed_items_dedup_through_canonicalization() -> None:
    a = _item(url="https://x.example/story?utm_campaign=z")
    b = _item(url="https://x.example/story")
    assert dedup_key(a) == dedup_key(b)


def test_query_param_order_does_not_change_identity() -> None:
    # query-param order is not part of a URL's identity → same canonical / dedup key
    assert canonical_url("https://x.example/story?b=2&a=1") == canonical_url(
        "https://x.example/story?a=1&b=2"
    )
    assert dedup_key(_item(url="https://x.example/s?b=2&a=1")) == dedup_key(
        _item(url="https://x.example/s?a=1&b=2")
    )


# --- seen-items store ------------------------------------------------------


def test_mark_and_is_seen_roundtrip_idempotent(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    assert is_seen(conn, "sub1", "k1") is False
    assert mark_seen(conn, "sub1", "k1") is True  # newly inserted
    assert is_seen(conn, "sub1", "k1") is True
    assert mark_seen(conn, "sub1", "k1") is False  # already present (set semantics)


def test_seen_is_per_subscription(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    mark_seen(conn, "subA", "k1")
    assert is_seen(conn, "subA", "k1") is True
    assert is_seen(conn, "subB", "k1") is False  # independent per subscription


# --- set-based selection ---------------------------------------------------


def test_reorder_does_not_re_emit_old_items(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    poll1 = parse_feed(fixture_path("feeds/rss_sample.xml").read_bytes())
    assert len(select_new_items(conn, "sub1", poll1)) == 3  # all new on first poll
    mark_items_seen(conn, "sub1", poll1)

    # next poll: same items reordered + one brand-new item → only the new one emits
    new_item = _item(guid="sec-press-2026-102", url="https://www.sec.gov/p/102")
    poll2 = [poll1[2], poll1[0], new_item, poll1[1]]
    fresh = select_new_items(conn, "sub1", poll2)
    assert [i.guid for i in fresh] == ["sec-press-2026-102"]


def test_intra_batch_duplicates_emit_once(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    dup = _item(guid="g-dup", url="https://x/1")
    out = select_new_items(conn, "sub1", [dup, dup, _item(guid="g-other")])
    assert [i.guid for i in out] == ["g-dup", "g-other"]


def test_marking_one_subscription_does_not_affect_another(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    items = [_item(guid="g1"), _item(guid="g2")]
    mark_items_seen(conn, "subA", items)
    assert select_new_items(conn, "subA", items) == []  # all seen for A
    assert len(select_new_items(conn, "subB", items)) == 2  # all new for B

    now = datetime(2026, 6, 9, tzinfo=UTC)
    assert mark_seen(conn, "subB", "g1", first_seen=now) is True
