"""Per-domain risk-control circuit breaker (owner 2026-07-21).

The 2026-07-21 production audit: bilibili answers 412 ("Request is blocked")
to this exit IP, the block is HOUR-scale and IP-wide — yet every item retried
independently on a 10-minute clock, so the worker kept knocking on a door that
was locked for the whole building. Lesson from crawl4ai's dispatcher design:
politeness is per-DOMAIN, not per-item. One risk-control failure freezes the
whole domain (1h, doubling to a 24h cap); one success clears it.

Persistent (SQLite) on purpose: per-item attempt budgets live in memory and
reset on restart — without a durable domain row, every restart re-hammers a
domain that banned us an hour ago.

This is NOT anti-bot evasion (§2.2 red line): the breaker only ever makes the
client MORE polite — fewer requests, same honest identity. A manual per-item
refresh deliberately bypasses the check (one explicit human probe is fine);
its outcome still updates the breaker for the background paths.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

_BASE_HOURS = 1.0
_CAP_HOURS = 24.0

# substrings (lowercased) in a typed failure reason that mean "the platform's
# risk control turned us away" — retrying soon makes it WORSE, not better
_RISK_MARKERS = (
    "412",
    "429",
    "request is blocked",
    "too many requests",
    "precondition failed",
    "rate limit",
)


def is_risk_control(reason: str | None, *, kind: str | None = None) -> bool:
    """Whether a typed failure is platform risk control (vs. an ordinary
    network/parse error). Matches the failure kind first, then reason text."""
    if kind == "anti_bot":
        return True
    if not reason:
        return False
    lowered = reason.lower()
    return any(marker in lowered for marker in _RISK_MARKERS)


def blocked_until(conn: sqlite3.Connection, domain: str | None) -> datetime | None:
    """The moment this domain's freeze lifts — or None (not frozen / expired).
    An expired row is left in place: it carries the consecutive count so a
    follow-up failure escalates instead of restarting at one hour."""
    if not domain:
        return None
    row = conn.execute(
        "SELECT blocked_until FROM domain_backoff WHERE domain = ?", (domain,)
    ).fetchone()
    if row is None:
        return None
    until = datetime.fromisoformat(row["blocked_until"])
    return until if until > datetime.now(UTC) else None


def record_risk_control(
    conn: sqlite3.Connection,
    domain: str | None,
    reason: str,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """A risk-control failure landed on this domain: freeze it, doubling the
    previous freeze (1h → 2h → … → 24h cap). Returns the new lift time."""
    if not domain:
        return None
    now = now or datetime.now(UTC)
    row = conn.execute(
        "SELECT consecutive FROM domain_backoff WHERE domain = ?", (domain,)
    ).fetchone()
    consecutive = (int(row["consecutive"]) + 1) if row is not None else 1
    hours = min(_BASE_HOURS * (2 ** (consecutive - 1)), _CAP_HOURS)
    until = now + timedelta(hours=hours)
    conn.execute(
        "INSERT INTO domain_backoff (domain, blocked_until, consecutive, last_reason, updated_at)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(domain) DO UPDATE SET blocked_until = excluded.blocked_until,"
        "   consecutive = excluded.consecutive, last_reason = excluded.last_reason,"
        "   updated_at = excluded.updated_at",
        (domain, until.isoformat(), consecutive, reason[:500], now.isoformat()),
    )
    conn.commit()
    return until


def record_success(conn: sqlite3.Connection, domain: str | None) -> None:
    """A request to this domain succeeded — the block (and its escalation
    history) is over."""
    if not domain:
        return
    conn.execute("DELETE FROM domain_backoff WHERE domain = ?", (domain,))
    conn.commit()
