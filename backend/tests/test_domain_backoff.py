"""Per-domain risk-control circuit breaker (2026-07-21 audit): one 412 freezes
the whole domain on an escalating clock; a success clears it; the state
survives a restart because it lives in SQLite, not process memory."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.db.engine import init_db
from app.tracking.domain_backoff import (
    blocked_until,
    is_risk_control,
    record_risk_control,
    record_success,
)

NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)


def test_freeze_escalates_and_caps(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    first = record_risk_control(conn, "bilibili.com", "412", now=NOW)
    assert first == NOW + timedelta(hours=1)
    second = record_risk_control(conn, "bilibili.com", "412", now=NOW)
    assert second == NOW + timedelta(hours=2)
    for _ in range(10):  # escalation caps at 24h, never unbounded
        last = record_risk_control(conn, "bilibili.com", "412", now=NOW)
    assert last == NOW + timedelta(hours=24)


def test_blocked_until_expires_on_its_own(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    past = datetime.now(UTC) - timedelta(hours=2)
    record_risk_control(conn, "bilibili.com", "412", now=past)  # 1h freeze, long over
    assert blocked_until(conn, "bilibili.com") is None
    # ...but the escalation history survives: the NEXT failure doubles
    until = record_risk_control(conn, "bilibili.com", "412", now=NOW)
    assert until == NOW + timedelta(hours=2)


def test_success_clears_the_freeze_and_history(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    record_risk_control(conn, "bilibili.com", "412")
    record_success(conn, "bilibili.com")
    assert blocked_until(conn, "bilibili.com") is None
    # history gone too — a fresh failure starts back at one hour
    until = record_risk_control(conn, "bilibili.com", "412", now=NOW)
    assert until == NOW + timedelta(hours=1)


def test_unrelated_domain_is_never_frozen(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    record_risk_control(conn, "bilibili.com", "412")
    assert blocked_until(conn, "sec.gov") is None
    assert blocked_until(conn, None) is None


def test_is_risk_control_matches_platform_blocks_only() -> None:
    assert is_risk_control("Request is blocked by server (412), please wait")
    assert is_risk_control("HTTP Error 412: Precondition Failed")
    assert is_risk_control("Client error '429 Too Many Requests' for url …")
    assert is_risk_control("whatever", kind="anti_bot")
    assert not is_risk_control("SSL: UNEXPECTED_EOF_WHILE_READING")  # network, not a ban
    assert not is_risk_control("no main text extracted")
    assert not is_risk_control(None)
