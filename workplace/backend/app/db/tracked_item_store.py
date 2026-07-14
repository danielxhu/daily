"""Tracked-item store (M15.1a, v0.12 P0 / Stage 15 gate).

The first-class persistence for tracked source items: a row is written the moment
the poll DISCOVERS an item, before any ingestion/extraction/scoring — so P0
visibility never depends on the deep-verification path (§2.4). Statuses then
track the item's own lifecycle:

* ``new``      — discovered this poll, pipeline still running (or crashed mid-poll:
                 the row honestly says "seen, not yet processed").
* ``fetched``  — ingestion succeeded; content is in hand. Deep-check failure does
                 NOT change this — it only sets ``degraded_reason``.
* ``failed``   — typed ingestion failure (`failure_kind` + the §6.6 kind→action map
                 drive the UI copy); the item stays visible with its link.
* ``deferred`` — M14.5 first-check transcription deferral; the next check
                 re-discovers the item (same PK) and processes it.

Keyed (subscription_id, item_key) exactly like ``seen_items``, so a re-discovered
item UPDATES its row (keeping id/first_seen) instead of duplicating.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Literal
from uuid import uuid4

from app.ingestion.domains import normalize_domain
from app.schemas.models import ItemEnrichment, SourceFailureKind, TrackedItemCard
from app.tiering import assign_tier
from app.tracking.dedup import dedup_key
from app.tracking.feed import FeedItem

TrackedItemStatus = Literal["new", "fetched", "failed", "deferred"]


def upsert_discovered(
    conn: sqlite3.Connection,
    *,
    subscription_id: str,
    board_id: str | None,
    item: FeedItem,
    now: datetime,
    module_id: str | None = None,
) -> None:
    """Record a just-dispatched item as discovered (status=new). A re-discovered
    item (M14.5 deferral re-queue) keeps its id/first_seen and resets to new;
    its module membership refreshes to the source's CURRENT module (M15.1)."""
    key = dedup_key(item)
    row = conn.execute(
        "SELECT 1 FROM tracked_items WHERE subscription_id = ? AND item_key = ?",
        (subscription_id, key),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO tracked_items (subscription_id, item_key, id, board_id, module_id,"
            " url, title, domain, published, first_seen, last_status_at, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')",
            (
                subscription_id,
                key,
                uuid4().hex,
                board_id,
                module_id,
                item.url,
                item.title,
                normalize_domain(item.url) if item.url else None,
                item.published.isoformat() if item.published else None,
                now.isoformat(),
                now.isoformat(),
            ),
        )
    else:
        conn.execute(
            "UPDATE tracked_items SET status = 'new', failure_kind = NULL,"
            " degraded_reason = NULL, module_id = ?, last_status_at = ?"
            " WHERE subscription_id = ? AND item_key = ?",
            (module_id, now.isoformat(), subscription_id, key),
        )
    conn.commit()


def set_status_by_url(
    conn: sqlite3.Connection,
    *,
    subscription_id: str,
    item_key: str,
    status: TrackedItemStatus,
    now: datetime,
    failure_kind: SourceFailureKind | None = None,
    degraded_reason: str | None = None,
) -> None:
    """Update one item's lifecycle status after the poll processed (or deferred,
    or failed to fetch) it. Never deletes — visibility is the point."""
    conn.execute(
        "UPDATE tracked_items SET status = ?, failure_kind = ?, degraded_reason = ?,"
        " last_status_at = ? WHERE subscription_id = ? AND item_key = ?",
        (status, failure_kind, degraded_reason, now.isoformat(), subscription_id, item_key),
    )
    conn.commit()


def _normalized_title(title: str | None) -> str | None:
    """Dup/repost matching key (M15.4): lowercased, whitespace-collapsed. Cheap and
    deterministic — a HINT for triage, deliberately not fuzzy matching."""
    if not title:
        return None
    collapsed = " ".join(title.lower().split())
    return collapsed or None


def _row_to_card(
    conn: sqlite3.Connection, row: sqlite3.Row, *, similar_count: int = 0
) -> TrackedItemCard:
    domain = row["domain"]
    return TrackedItemCard(
        id=row["id"],
        board_id=row["board_id"],
        module_id=row["module_id"],
        url=row["url"],
        title=row["title"],
        domain=domain,
        # P1 lite signal, code-first (§2.4) — derived at read time; wiring the
        # human tier-override store in here can come later if needed
        tier=assign_tier(domain, url=row["url"]) if domain else None,
        published=datetime.fromisoformat(row["published"]) if row["published"] else None,
        first_seen=datetime.fromisoformat(row["first_seen"]),
        status=row["status"],
        failure_kind=row["failure_kind"],
        degraded_reason=row["degraded_reason"],
        # DEPRECATED single-language briefing (M16.3) — carried for compat only
        summary=row["summary"],
        # M16.3: bilingual enrichment; None = pending (the UI says so honestly)
        enrichment=(
            ItemEnrichment.model_validate(json.loads(row["enrichment"]))
            if row["enrichment"]
            else None
        ),
        content_available=row["content_excerpt"] is not None,
        similar_count=similar_count,
    )


def recent_tracked_items(
    conn: sqlite3.Connection,
    *,
    since: datetime,
    until: datetime | None = None,
    board_id: str | None = None,
    limit: int = 100,
) -> list[TrackedItemCard]:
    """Items discovered in [since, until), newest first by published (fallback
    first_seen) — the digest's `tracked` channel (M15.1a). Read-only, zero LLM."""
    clauses = ["first_seen >= ?"]
    params: list[object] = [since.isoformat()]
    if until is not None:
        clauses.append("first_seen < ?")
        params.append(until.isoformat())
    if board_id is not None:
        clauses.append("board_id = ?")
        params.append(board_id)
    params.append(limit)
    rows = conn.execute(
        "SELECT * FROM tracked_items WHERE "
        + " AND ".join(clauses)
        + " ORDER BY COALESCE(published, first_seen) DESC LIMIT ?",
        params,
    ).fetchall()
    # M15.4 dup/repost hint (code-first, §2.4): count the OTHER domains in this
    # result set carrying the same normalized title. Same-domain repeats don't
    # count — the hint suggests cross-source echo, mirroring the deep path's
    # domain-counting philosophy without pretending to be corroboration.
    domains_by_title: dict[str, set[str]] = {}
    for r in rows:
        key = _normalized_title(r["title"])
        if key is not None and r["domain"]:
            domains_by_title.setdefault(key, set()).add(r["domain"])
    cards = []
    for r in rows:
        key = _normalized_title(r["title"])
        similar = 0
        if key is not None and r["domain"]:
            similar = len(domains_by_title.get(key, set()) - {r["domain"]})
        cards.append(_row_to_card(conn, r, similar_count=similar))
    return cards


# a discussion/re-enrich grounding needs the lede and body, not unbounded pages
_CONTENT_EXCERPT_CAP = 20_000


def set_item_enrichment(
    conn: sqlite3.Connection,
    *,
    subscription_id: str,
    item_key: str,
    enrichment: ItemEnrichment,
) -> None:
    """Persist the bilingual enrichment (M16.3). Only called with a REAL result —
    a failed generation writes nothing (the column stays NULL; the UI shows an
    honest pending state and the persisted excerpt allows a manual re-enrich)."""
    conn.execute(
        "UPDATE tracked_items SET enrichment = ? WHERE subscription_id = ? AND item_key = ?",
        (
            json.dumps(enrichment.model_dump(), ensure_ascii=False),
            subscription_id,
            item_key,
        ),
    )
    conn.commit()


def set_item_excerpt(
    conn: sqlite3.Connection,
    *,
    subscription_id: str,
    item_key: str,
    text: str,
    method: str | None = None,
) -> None:
    """Persist the item's content excerpt (M16.3, capped) — code-only, written for
    every fetched item even when enrichment fails, so the per-item discussion
    (M16.5) and the manual re-enrich (M16.4) have grounding material. `method`
    (M16.4) records HOW the content was obtained — provenance for the detail page."""
    excerpt = text.strip()[:_CONTENT_EXCERPT_CAP]
    if not excerpt:
        return
    conn.execute(
        "UPDATE tracked_items SET content_excerpt = ?, extraction_method = ?"
        " WHERE subscription_id = ? AND item_key = ?",
        (excerpt, method, subscription_id, item_key),
    )
    conn.commit()


def get_item_excerpt(conn: sqlite3.Connection, item_id: str) -> str | None:
    row = conn.execute(
        "SELECT content_excerpt FROM tracked_items WHERE id = ?", (item_id,)
    ).fetchone()
    return row["content_excerpt"] if row else None


def search_tracked_items(
    conn: sqlite3.Connection, query: str, *, limit: int = 5
) -> list[TrackedItemCard]:
    """Keyword search over tracked items (M15.2, v0.12 P0 "searchable"): the same
    CJK-aware token-overlap scoring as saved notes, over title + bilingual
    enrichment (summaries/tags/entities ride in its JSON text) + domain (the
    deprecated single-language summary column still counts for legacy rows).
    Deterministic, zero LLM, single-operator scale — Python scoring is fine."""
    from app.db.knowledge_store import _query_tokens  # shared bilingual tokenizer

    tokens = _query_tokens(query)
    if not tokens:
        return []
    rows = conn.execute("SELECT * FROM tracked_items").fetchall()
    scored: list[tuple[int, str, sqlite3.Row]] = []
    for row in rows:
        haystack = " ".join(
            str(v) for v in (row["title"], row["summary"], row["enrichment"], row["domain"]) if v
        ).lower()
        score = sum(1 for tok in tokens if tok in haystack)
        if score > 0:
            scored.append((score, str(row["first_seen"]), row))
    scored.sort(key=lambda item: item[1], reverse=True)  # newest first …
    scored.sort(key=lambda item: -item[0])  # … then most-distinct-tokens first
    return [_row_to_card(conn, row) for _, _, row in scored[:limit]]


def get_tracked_item_row(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row | None:
    """One item's raw row by public id (M15.5 manual deep check)."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM tracked_items WHERE id = ?", (item_id,)
    ).fetchone()
    return row


def tracked_item_card_by_id(conn: sqlite3.Connection, item_id: str) -> TrackedItemCard | None:
    """One item as its API card (M15.5). `similar_count` is a view-window signal,
    so a single-item read reports 0 rather than recomputing a window."""
    row = get_tracked_item_row(conn, item_id)
    return _row_to_card(conn, row) if row is not None else None


def related_tracked_items(
    conn: sqlite3.Connection, item_id: str, *, limit: int = 6
) -> list[TrackedItemCard]:
    """Related items for the detail page (M16.4) — cheap, deterministic hints in
    priority order: (1) the same normalized title on OTHER domains (the M15.4
    dup/repost echo), (2) recent items from the same domain, (3) recent items in
    the same module. Never a corroboration signal — just "you may also want to
    open these"."""
    me = conn.execute("SELECT * FROM tracked_items WHERE id = ?", (item_id,)).fetchone()
    if me is None:
        return []
    rows = conn.execute(
        "SELECT * FROM tracked_items WHERE id != ? ORDER BY COALESCE(published, first_seen) DESC",
        (item_id,),
    ).fetchall()
    my_title = _normalized_title(me["title"])
    picked: list[sqlite3.Row] = []
    seen: set[str] = set()

    def take(pred) -> None:  # type: ignore[no-untyped-def]
        for r in rows:
            if len(picked) >= limit:
                return
            if r["id"] in seen or not pred(r):
                continue
            seen.add(r["id"])
            picked.append(r)

    if my_title is not None:
        take(lambda r: _normalized_title(r["title"]) == my_title and r["domain"] != me["domain"])
    if me["domain"]:
        take(lambda r: r["domain"] == me["domain"])
    if me["module_id"]:
        take(lambda r: r["module_id"] == me["module_id"])
    return [_row_to_card(conn, r) for r in picked]
