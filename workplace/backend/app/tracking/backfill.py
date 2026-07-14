"""Backfill bilingual AI summaries for already-stored items (owner 2026-07-10).

Every tracked item whose content excerpt is already on disk but whose enrichment
is missing (the DeepSeek balance ran dry, so poll-time generation silently
failed) gets ONE flash call from its STORED text — no re-fetching, no network
beyond the LLM. Items without a stored excerpt are skipped (refresh them from
the detail page instead). Fails fast on a balance/auth error: burning 3 retries
x hundreds of items against a dead account helps nobody.

Run:  cd backend && .venv/bin/python -m app.tracking.backfill
"""

from __future__ import annotations

import sqlite3
import sys

from app.clients.base import LLMClient
from app.clients.deepseek import get_llm_client
from app.core.config import get_settings
from app.db.engine import init_db
from app.db.tracked_item_store import set_item_enrichment
from app.ingestion.domains import normalize_domain
from app.tracking.summarize import enrich_fetched_item

_FATAL_MARKERS = ("Insufficient Balance", "401", "402", "invalid_request_error")


def backfill(conn: sqlite3.Connection, llm: LLMClient) -> tuple[int, int]:
    """Summarize every stored-text/no-summary item; returns (ok, failed)."""
    rows = conn.execute(
        "SELECT id, subscription_id, item_key, url, title, content_excerpt"
        " FROM tracked_items"
        " WHERE content_excerpt IS NOT NULL AND (enrichment IS NULL"
        # 2026-07-10: bilingual TITLES joined the enrichment — refresh cached
        # enrichments that predate them so the locale toggle carries the title
        " OR json_extract(enrichment, '$.title_en') IS NULL)"
        " ORDER BY first_seen DESC"
    ).fetchall()
    print(f"{len(rows)} item(s) need an AI summary or bilingual title — backfilling…")
    ok = failed = 0
    for i, row in enumerate(rows, 1):
        errors: list[str] = []
        enrichment = enrich_fetched_item(
            row["content_excerpt"],
            title=row["title"],
            domain=normalize_domain(row["url"]) if row["url"] else None,
            llm=llm,
            errors=errors,
        )
        title = (row["title"] or row["id"])[:60]
        if enrichment is None:
            failed += 1
            reason = errors[-1] if errors else "unusable model output"
            print(f"  [{i}/{len(rows)}] FAIL  {title} — {reason}")
            if any(marker in reason for marker in _FATAL_MARKERS):
                print("aborting: the API account itself is failing — fix the key/balance first")
                break
        else:
            set_item_enrichment(
                conn,
                subscription_id=row["subscription_id"],
                item_key=row["item_key"],
                enrichment=enrichment,
            )
            ok += 1
            print(f"  [{i}/{len(rows)}] ok    {title}")
    print(f"done: {ok} summarized, {failed} failed, {len(rows) - ok - failed} untouched")
    return ok, failed


def main() -> int:
    _, failed = backfill(init_db(get_settings().sqlite_path), get_llm_client())
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
