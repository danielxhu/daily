"""M7.8 — source health + anomaly (SSOT §6.6).

Failure-matrix classification (404→gone, 403/429→rate_limited, parse/render→unfit,
timeout/connection→network), the broad-anomaly discriminator (many fail at once →
system-side, subscriptions left untouched), per-subscription backoff bookkeeping,
and a user-facing next step per subscription-failure kind. Scope: health only — no
rolling-window/scoring (M7.9)."""

from __future__ import annotations

import typing
from pathlib import Path

from app.db.engine import init_db
from app.db.subscription_store import (
    UNHEALTHY_AFTER,
    create_subscription,
    get_subscription,
    record_poll_failure,
    record_poll_success,
)
from app.schemas.models import SubscriptionFailureKind
from app.tracking.feed import FeedParseError
from app.tracking.health import (
    SUBSCRIPTION_NEXT_ACTION,
    SystemAnomaly,
    apply_poll_health,
    classify_subscription_failure,
    is_system_anomaly,
    subscription_next_action,
)
from app.tracking.poll import PollOutcome


class _HTTPError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _HTTPXLikeError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__("status error")
        self.response = _Response(status_code)


# --- failure matrix --------------------------------------------------------


def test_classify_failure_matrix() -> None:
    assert classify_subscription_failure(_HTTPError(404)) == "gone"
    assert classify_subscription_failure(_HTTPError(410)) == "gone"
    assert classify_subscription_failure(_HTTPError(403)) == "rate_limited"
    assert classify_subscription_failure(_HTTPError(429)) == "rate_limited"
    # httpx-style: status lives on exc.response.status_code
    assert classify_subscription_failure(_HTTPXLikeError(404)) == "gone"
    assert classify_subscription_failure(FeedParseError("bad xml")) == "parse_or_render_unfit"
    assert classify_subscription_failure(TimeoutError("slow")) == "network"
    assert classify_subscription_failure(ConnectionError("refused")) == "network"
    # ambiguous → network (retry, don't declare dead)
    assert classify_subscription_failure(RuntimeError("???")) == "network"


def test_every_subscription_failure_kind_has_a_next_action() -> None:
    kinds = set(typing.get_args(SubscriptionFailureKind))
    assert kinds == set(SUBSCRIPTION_NEXT_ACTION)
    assert all(subscription_next_action(k) for k in kinds)  # all non-empty


# --- anomaly discriminator -------------------------------------------------


def test_is_system_anomaly() -> None:
    assert is_system_anomaly(total=3, failed=3) is True  # all of a non-trivial set
    assert is_system_anomaly(total=5, failed=3) is True  # majority, ≥3
    assert is_system_anomaly(total=5, failed=2) is False  # below the floor
    assert is_system_anomaly(total=5, failed=1) is False  # isolated
    assert is_system_anomaly(total=2, failed=2) is False  # too few to call system-wide


# --- per-subscription bookkeeping + backoff --------------------------------


def test_failure_increments_then_marks_unhealthy_and_backs_off(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(conn, input_url="https://x/feed", mode="direct")
    assert sub.interval_minutes == 60

    for _ in range(UNHEALTHY_AFTER - 1):  # first 2 failures stay healthy
        record_poll_failure(conn, sub.id, "network", "timeout")
    healthy = get_subscription(conn, sub.id)
    assert healthy is not None
    assert healthy.consecutive_failures == 2
    assert healthy.health == "ok" and healthy.interval_minutes == 60

    third = record_poll_failure(conn, sub.id, "gone", "404")
    assert third is not None
    assert third.consecutive_failures == 3
    assert third.health == "unhealthy"
    assert third.interval_minutes == 120  # backed off (doubled) at the threshold
    assert third.subscription_failure_kind == "gone" and third.last_error == "404"

    fourth = record_poll_failure(conn, sub.id, "gone", "404")
    assert fourth is not None and fourth.interval_minutes == 240  # doubles again


def test_success_resets_failure_bookkeeping(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(conn, input_url="https://x/feed", mode="direct")
    record_poll_failure(conn, sub.id, "network", "timeout")
    record_poll_success(conn, sub.id)
    healed = get_subscription(conn, sub.id)
    assert healed is not None
    assert healed.consecutive_failures == 0 and healed.health == "ok"
    assert healed.last_error is None and healed.subscription_failure_kind is None


def test_record_failure_on_missing_subscription_returns_none(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    assert record_poll_failure(conn, "ghost", "network", "x") is None


# --- batch application ------------------------------------------------------


def _ok(sub_id: str) -> PollOutcome:
    return PollOutcome(sub_id, ok=True, new_count=1, dispatched=["u"])


def _fail(sub_id: str, exc: BaseException) -> PollOutcome:
    return PollOutcome(sub_id, ok=False, new_count=0, dispatched=[], error=str(exc), exc=exc)


def test_apply_health_isolated_failure_updates_only_that_subscription(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    a = create_subscription(conn, input_url="https://a/feed", mode="direct")
    b = create_subscription(conn, input_url="https://b/feed", mode="direct")
    c = create_subscription(conn, input_url="https://c/feed", mode="direct")

    anomaly = apply_poll_health(conn, [_ok(a.id), _ok(b.id), _fail(c.id, _HTTPError(404))])
    assert anomaly is None  # 1 of 3 → isolated, not system-wide

    failing = get_subscription(conn, c.id)
    assert failing is not None
    assert failing.consecutive_failures == 1 and failing.subscription_failure_kind == "gone"
    healthy = get_subscription(conn, a.id)
    assert healthy is not None and healthy.consecutive_failures == 0


def test_apply_health_broad_network_failure_is_anomaly_and_leaves_state_untouched(
    tmp_path: Path,
) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    subs = [create_subscription(conn, input_url=f"https://{n}/feed", mode="direct") for n in "abc"]
    outcomes = [_fail(s.id, TimeoutError("down")) for s in subs]

    anomaly = apply_poll_health(conn, outcomes)
    assert anomaly == SystemAnomaly(total=3, failed=3)
    # §6.6: no subscription is marked unhealthy on the strength of a system anomaly
    for s in subs:
        row = get_subscription(conn, s.id)
        assert row is not None
        assert row.consecutive_failures == 0 and row.health == "ok"


def test_broad_gone_failures_are_not_an_anomaly_and_are_each_marked(tmp_path: Path) -> None:
    # 3 sources all 404 at once is NOT a system outage — each is genuinely gone and
    # must be marked so the user is prompted to replace it (§6.6 failure matrix).
    conn = init_db(str(tmp_path / "daily.db"))
    subs = [create_subscription(conn, input_url=f"https://{n}/feed", mode="direct") for n in "abc"]

    anomaly = apply_poll_health(conn, [_fail(s.id, _HTTPError(404)) for s in subs])
    assert anomaly is None  # gone is per-source, never a system anomaly
    for s in subs:
        row = get_subscription(conn, s.id)
        assert row is not None
        assert row.consecutive_failures == 1 and row.subscription_failure_kind == "gone"


def test_gone_mixed_with_broad_network_still_flags_anomaly(tmp_path: Path) -> None:
    # one dead source + a broad network outage: the system-side failures (≥3, majority)
    # still raise the anomaly; the gone one is left for a later, non-anomalous poll.
    conn = init_db(str(tmp_path / "daily.db"))
    subs = [create_subscription(conn, input_url=f"https://{n}/feed", mode="direct") for n in "abcd"]
    outcomes = [_fail(subs[0].id, _HTTPError(404))] + [
        _fail(s.id, TimeoutError("down")) for s in subs[1:]
    ]
    anomaly = apply_poll_health(conn, outcomes)
    assert anomaly == SystemAnomaly(total=4, failed=3)  # 3 network failures, gone excluded
