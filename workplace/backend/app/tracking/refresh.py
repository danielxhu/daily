"""Manual per-item refresh (M16.4, v0.13).

The user-triggered "fetch & summarize" for ONE tracked item: re-fetch its URL,
persist the content excerpt (code-only), and generate the bilingual enrichment.
This is how a legacy pre-v0.13 item (no stored text, honest pending state) gets
its summary — and it is deliberately NOT a deep check: no claim extraction, no
alignment, no scoring, no memory writes. The verification engine stays dormant
(v0.13); refresh only feeds the tracking/knowledge read surface.

Synchronous, one item per call (single-operator, local-first — same stance as
deep_check), but NEVER whisper (owner 2026-07-19): a caption-less video is
marked deferred for the background worker instead of downloading audio inside
the request. Lock discipline (owner 2026-07-13 "这他妈是我自己点了才显示…"): the
slow parts — network fetch, the LLM call — run OUTSIDE the poll mutex;
only the millisecond DB writes take it (blocking, bounded wait). The old
whole-call lock meant one background transcription blocked every open page's
auto-refresh with an instant 409, which read as "automatic did nothing".
Failures are typed and loud:
* fetch failure → the existing row is left UNTOUCHED (a legacy fetched item must
  not lose its status because a retry hit a paywall) and the error surfaces;
* enrichment failure AFTER a good fetch → the excerpt is kept (the retry is now
  cheap and the discussion grounding exists) and the error surfaces.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from app.clients.base import LLMClient
from app.db.tracked_item_store import (
    get_tracked_item_row,
    set_item_enrichment,
    set_item_excerpt,
    set_status_by_url,
    tracked_item_card_by_id,
)
from app.ingestion.domains import normalize_domain
from app.ingestion.ingest import IngestFn
from app.schemas.models import SourceRequest, TrackedItemCard
from app.tracking.runtime import _POLL_MUTEX, PollInProgressError
from app.tracking.summarize import enrich_fetched_item


class RefreshError(ValueError):
    """The item cannot be refreshed (unknown id, or no URL to re-fetch)."""


class RefreshFailedError(RuntimeError):
    """The refresh ran but could not complete — typed, retryable (HTTP 502)."""


# writes are milliseconds; a running poll finishes within this comfortably. The
# module constant exists so tests can shrink it to exercise the timeout path.
_LOCK_TIMEOUT_SECONDS = 30.0


@contextmanager
def _locked_writes() -> Iterator[None]:
    if not _POLL_MUTEX.acquire(timeout=_LOCK_TIMEOUT_SECONDS):
        raise PollInProgressError("the tracker is busy — try again in a moment")
    try:
        yield
    finally:
        _POLL_MUTEX.release()


def refresh_item(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    llm: LLMClient,
    ingest: IngestFn,
    now: datetime | None = None,
) -> TrackedItemCard:
    """Fetch + excerpt + bilingual enrichment for one tracked item; returns the
    updated card. Raises RefreshError (bad target), PollInProgressError (mutex),
    or RefreshFailedError (fetch/enrichment failed — state stays honest)."""
    row = get_tracked_item_row(conn, item_id)
    if row is None:
        raise RefreshError(f"no such tracked item: {item_id}")
    url = row["url"]
    if not url:
        raise RefreshError("this item has no URL to re-fetch (pasted/keyless item)")

    now = now or datetime.now(UTC)
    sub_id: str = row["subscription_id"]
    item_key: str = row["item_key"]
    # slow phase 1: the fetch/transcription — NO lock held
    result = ingest(SourceRequest(kind="url", url=url))
    if result.status == "ok" and result.source is not None:
        src = result.source
        text, domain = src.raw_text, src.domain
        with _locked_writes():
            set_item_excerpt(
                conn,
                subscription_id=sub_id,
                item_key=item_key,
                text=text,
                method=src.extraction_method,
            )
            # a successful fetch settles the lifecycle honestly: a previously-failed
            # item is now fetched; a fetched item stays fetched. degraded_reason is
            # cleared — the content is in hand and the briefing is regenerated below.
            set_status_by_url(
                conn, subscription_id=sub_id, item_key=item_key, status="fetched", now=now
            )
    elif row["content_excerpt"]:
        # owner 2026-07-10: a poll stored this item's text but its summary was
        # never generated (LLM outage), and the site now blocks re-fetching —
        # the stored text is still perfectly good grounding. Summarize from it
        # instead of failing on a fetch we don't actually need.
        text, domain = row["content_excerpt"], normalize_domain(url)
    elif result.failure is not None and result.failure.kind == "transcription_deferred":
        # owner 2026-07-19 ("这他妈抓了快十分钟了"): a caption-less video means
        # audio download + whisper — minutes of throttled CDN trickle that used
        # to run INSIDE this request. Never transcribe synchronously: mark the
        # item deferred and return; the background worker (one per 30s tick)
        # owns transcription, and the UI polls the item until content lands.
        with _locked_writes():
            set_status_by_url(
                conn,
                subscription_id=sub_id,
                item_key=item_key,
                status="deferred",
                now=now,
                failure_kind="transcription_deferred",
            )
        card = tracked_item_card_by_id(conn, item_id)
        assert card is not None
        return card
    else:
        kind = result.failure.kind if result.failure else "timeout"
        # the existing row is untouched — a failed RETRY must not downgrade
        # what the user already has (status, old excerpt, old enrichment)
        raise RefreshFailedError(f"fetch failed ({kind}) — try again later")
    # slow phase 2: the LLM call — NO lock held
    llm_errors: list[str] = []
    enrichment = enrich_fetched_item(
        text, title=row["title"], domain=domain, llm=llm, errors=llm_errors
    )
    if enrichment is None:
        reason = f" ({llm_errors[-1]})" if llm_errors else ""
        raise RefreshFailedError(
            "the text was fetched and stored, but the summary generation "
            f"failed{reason} — try again"
        )
    with _locked_writes():
        set_item_enrichment(conn, subscription_id=sub_id, item_key=item_key, enrichment=enrichment)
    card = tracked_item_card_by_id(conn, item_id)
    assert card is not None  # the row existed above and is never deleted
    return card
