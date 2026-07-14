"""Feed-item dedup keys + set-based new-item selection (M7.6, SSOT §6.2 / §6.3).

The dedup key for a feed entry is, in precedence order (§6.2): its `id`/`guid`,
else its canonicalized URL, else a content hash. Selection is **set-based** against
the seen-items store — order-independent, so an RSS reorder never re-emits an old
item (there is no single `last_seen` cursor, §6.3).

Scope: key computation + selection only — no scheduler / poll loop (M7.7), no
ingestion dispatch. Marking happens via `mark_items_seen` when the caller decides.
"""

from __future__ import annotations

import hashlib
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.db.seen_store import is_seen, mark_seen
from app.tracking.feed import FeedItem

_TRACKING_PARAMS = frozenset(
    {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src", "spm"}
)


def _is_tracking_param(key: str) -> bool:
    k = key.lower()
    return k in _TRACKING_PARAMS or k.startswith("utm_")


def canonical_url(url: str) -> str:
    """A stable form of a URL for dedup: lowercased scheme+host, fragment dropped,
    tracking params (utm_*, fbclid, …) stripped, trailing slash removed."""
    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    # sort retained params: query-param order is not part of a URL's identity, so
    # ?a=1&b=2 and ?b=2&a=1 must canonicalize identically (else false-new items).
    kept = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(k)
    )
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, host, path, urlencode(kept), ""))


def dedup_key(item: FeedItem) -> str:
    """The item's dedup identity (§6.2): guid → canonical URL → content hash."""
    if item.guid:
        return item.guid
    if item.url:
        return canonical_url(item.url)
    basis = "\n".join(
        [
            item.title or "",
            item.summary or "",
            item.published.isoformat() if item.published else "",
        ]
    )
    return "sha256:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()


def select_new_items(
    conn: sqlite3.Connection, subscription_id: str, items: list[FeedItem]
) -> list[FeedItem]:
    """The items whose dedup key is not already in the seen-items set, deduped within
    the batch too. Read-only — call `mark_items_seen` to record them."""
    out: list[FeedItem] = []
    batch: set[str] = set()
    for item in items:
        key = dedup_key(item)
        if key in batch or is_seen(conn, subscription_id, key):
            continue
        batch.add(key)
        out.append(item)
    return out


def mark_items_seen(conn: sqlite3.Connection, subscription_id: str, items: list[FeedItem]) -> None:
    """Record each item's dedup key as seen for this subscription."""
    for item in items:
        mark_seen(conn, subscription_id, dedup_key(item))
