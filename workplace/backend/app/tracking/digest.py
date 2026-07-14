"""The digest read surface (SSOT §6.5 / FR-13; verification engine removed
2026-07-13 by owner decision).

`assemble_digest` builds the board-filterable recent view over the TRACKED
channel — what the user's sources published, with typed statuses and cached
bilingual AI summaries. Render is cache-only, zero LLM by signature (M14.7,
owner "为什么这么慢"): a page open can never bill or block on DeepSeek.
`digest_to_rss` renders the same channel as a minimal read-only RSS 2.0 feed.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

from app.core.config import DIGEST_WINDOW_DAYS
from app.db.tracked_item_store import recent_tracked_items
from app.schemas.models import DailyDigest


def assemble_digest(
    db: sqlite3.Connection,
    *,
    now: datetime,
    board_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    window_days: int = DIGEST_WINDOW_DAYS,
) -> DailyDigest:
    """Build the digest over the recent view window (default 30 days — M14.6,
    owner: "近期的所有变化,默认一个月", user-adjustable per request): the tracked
    items discovered in the window, newest first, optionally board-filtered.
    `until` bounds a date-scoped digest; otherwise it runs to now."""
    window_start = since if since is not None else now - timedelta(days=window_days)
    date = (until - timedelta(days=1)).date() if until is not None else now.date()
    tracked = recent_tracked_items(db, since=window_start, until=until, board_id=board_id)
    return DailyDigest(date=date, generated_at=now, tracked=tracked)


def digest_to_rss(digest: DailyDigest, *, title: str = "daily — source tracking digest") -> str:
    """Render the digest as a minimal read-only RSS 2.0 feed (FR-13): source
    domain, code-first tier, typed status, and the cached bilingual AI summary
    (labeled as restating the source). Cache-only: zero LLM (M14.7 invariant)."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        f"<title>{escape(title)}</title>",
        f"<pubDate>{escape(digest.generated_at.isoformat())}</pubDate>",
    ]
    for item in digest.tracked:
        meta = " · ".join(
            bit
            for bit in (
                item.domain,
                f"tier {item.tier}" if item.tier else None,
                item.status,
            )
            if bit
        )
        description = meta
        if item.enrichment is not None:
            description = (
                f"{meta} — AI summary (restates the source): "
                f"{item.enrichment.summary_zh} / {item.enrichment.summary_en}"
            )
        link = f"<link>{escape(item.url)}</link>" if item.url else ""
        parts.append(
            "<item>"
            f"<title>{escape(item.title or item.url or item.id)}</title>"
            f'<guid isPermaLink="false">{escape(item.id)}</guid>'
            f"{link}"
            f"<description>{escape(description)}</description>"
            "</item>"
        )
    parts.append("</channel></rss>")
    return "".join(parts)
