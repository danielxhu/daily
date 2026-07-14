"""Source health + anomaly (M7.8, SSOT §6.6).

A failing poll must not be blindly read as "the source is dead" — it may be daily's
own fetch problem, or a system-wide outage. Two discriminators (§6.6):

* **Scope** — one source vs. many. If many subscriptions fail at the same poll it is
  almost certainly system-side (network down, a dep, IP-wide rate-limit); raise ONE
  anomaly and **leave subscription states untouched**. An isolated failure is the
  source's (or our fetch method's) problem and updates that subscription's health.
* **Kind** — classify, don't just count: 404/410 → gone, 403/429 → rate-limited,
  fetched-but-unusable → fetch method unfit, timeout/connection → network.

Per-subscription bookkeeping (counters, unhealthy threshold, backoff) lives in
`subscription_store`; this module classifies failures, detects the broad anomaly,
maps each subscription-failure kind to a user-facing next step, and applies health
to a batch of poll outcomes. Scope: health only — no rolling-window/scoring (M7.9).

The per-item `SourceFailureKind → next_action` map (FR-2) already exists in
`ingestion.fetch_policy`; this is its subscription-level counterpart.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.db.subscription_store import record_poll_failure, record_poll_success
from app.schemas.models import SubscriptionFailureKind
from app.tracking.feed import FeedParseError
from app.tracking.poll import PollOutcome

# Below this many failures at one poll, failures are treated as isolated/per-source.
ANOMALY_MIN_FAILURES = 3

# A user-facing next step per subscription-failure kind ("the user sees a next step,
# not a log", §6.6) — the subscription-level analogue of FR-2's source next_action.
SUBSCRIPTION_NEXT_ACTION: dict[SubscriptionFailureKind, str] = {
    "gone": "Source looks gone (404/410). Replace or remove this subscription.",
    "rate_limited": "Rate-limited (403/429). daily will back off and retry — no action needed.",
    "parse_or_render_unfit": (
        "Fetched, but no usable content — this source may need a different fetch "
        "method; paste items manually if it persists."
    ),
    "network": "Network or timeout error. daily will retry on the next poll.",
    "system_anomaly": (
        "Many sources failed at once — likely a system-side issue (network or a "
        "dependency), not these sources."
    ),
    # M13.1 (beta P0-1): the feed lists new items but the article pages themselves
    # can't be fetched — the one recovery path is pasting the article text.
    "items_unfetchable": (
        "The feed works, but the articles themselves can't be fetched (anti-bot or "
        "paywall). Paste the article text on the Check page instead."
    ),
}


def subscription_next_action(kind: SubscriptionFailureKind) -> str:
    return SUBSCRIPTION_NEXT_ACTION[kind]


def _status_of(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def classify_subscription_failure(exc: BaseException) -> SubscriptionFailureKind:
    """Map a poll exception to a subscription-failure kind (§6.6 failure matrix)."""
    status = _status_of(exc)
    if status in (404, 410):  # dead URL / removed
        return "gone"
    if status in (403, 429):  # bot-blocked / rate-limited — back off, don't kill
        return "rate_limited"
    name = type(exc).__name__.lower()
    if isinstance(exc, FeedParseError) or "parse" in name or "render" in name or "empty" in name:
        return "parse_or_render_unfit"  # fetched but our method couldn't use it
    if isinstance(exc, TimeoutError | ConnectionError) or "timeout" in name or "connect" in name:
        return "network"
    return "network"  # ambiguous default: retry, don't declare the source dead


@dataclass(frozen=True)
class SystemAnomaly:
    """A broad simultaneous failure (§6.6) — surfaced once; no subscription is marked
    unhealthy on the strength of it."""

    total: int
    failed: int


def is_system_anomaly(total: int, failed: int) -> bool:
    """Broad simultaneous failure: a non-trivial number of sources (≥3) AND a
    majority of this poll failing together — read as system-side, not per-source."""
    return failed >= ANOMALY_MIN_FAILURES and failed * 2 >= total


def apply_poll_health(
    conn: sqlite3.Connection,
    outcomes: list[PollOutcome],
    item_failures: dict[str, str] | None = None,
) -> SystemAnomaly | None:
    """Update subscription health from a batch of poll outcomes. Failures are
    classified first: a broad anomaly is raised once and leaves every subscription
    untouched (§6.6) — but only **ambiguous/system-side** failures count toward it.
    A `gone` (404/410) source is definitively dead, never a system anomaly, so it is
    always marked (so the user is told to replace it). Otherwise the healthy ones are
    reset and each isolated failure is recorded (with backoff).

    `item_failures` (M13.1, beta P0-1): subscription_id → error summary for sources
    whose FEED polled fine but whose new items ALL failed ingestion (anti-bot /
    paywall article pages). These are recorded as `items_unfetchable` failures —
    never silently reset as successes — so the typed reason + next step reach the
    subscription row immediately. Item failures are per-source by nature (a site
    blocking article fetches), so they never count toward the system anomaly."""
    item_failures = item_failures or {}
    classified: list[tuple[PollOutcome, SubscriptionFailureKind]] = [
        (o, classify_subscription_failure(o.exc))
        for o in outcomes
        if not o.ok and o.exc is not None
    ]
    # only network / rate-limit / parse-render failures can be a system-wide outage
    # (§6.6: network down, IP-wide rate-limit, a dep bug). `gone` is per-source.
    system_side = [o for o, kind in classified if kind != "gone"]
    if is_system_anomaly(len(outcomes), len(system_side)):
        return SystemAnomaly(total=len(outcomes), failed=len(system_side))
    for outcome in outcomes:
        if outcome.ok and outcome.subscription_id not in item_failures:
            record_poll_success(conn, outcome.subscription_id)
    for outcome, kind in classified:
        record_poll_failure(conn, outcome.subscription_id, kind, outcome.error or "")
    for subscription_id, error in item_failures.items():
        record_poll_failure(conn, subscription_id, "items_unfetchable", error)
    return None
