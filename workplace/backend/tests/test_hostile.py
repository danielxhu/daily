"""M1B.4 — hostile-source classifier.

Maps a fetched response (status + body markers) to a typed `SourceFailureKind`
so the user is told to paste the text; we never bypass. A clean article → None."""

from __future__ import annotations

from app.ingestion.hostile import classify_hostile
from tests import fixtures_loader as fx


def test_cloudflare_body_is_anti_bot() -> None:
    body = fx.load_text("html/cloudflare_challenge.html")
    assert classify_hostile(status_code=200, body=body) == "anti_bot"


def test_paywall_body_is_paywall() -> None:
    body = fx.load_text("html/paywall_bloomberg.html")
    assert classify_hostile(status_code=200, body=body) == "paywall"


def test_login_body_is_login_required() -> None:
    body = fx.load_text("html/login_wall.html")
    assert classify_hostile(status_code=200, body=body) == "login_required"


def test_status_codes_map_to_kinds() -> None:
    assert classify_hostile(status_code=402) == "paywall"
    assert classify_hostile(status_code=401) == "login_required"
    assert classify_hostile(status_code=429) == "anti_bot"
    assert classify_hostile(status_code=403) == "fetch_blocked"
    assert classify_hostile(status_code=500) == "fetch_blocked"


def test_body_marker_overrides_ok_status() -> None:
    # an interstitial served with 200 is still hostile
    assert classify_hostile(status_code=200, body="Just a moment...") == "anti_bot"


def test_clean_article_is_not_hostile() -> None:
    body = fx.load_text("html/static_article.html")
    assert classify_hostile(status_code=200, body=body) is None


def test_mention_of_subscribe_is_not_a_false_positive() -> None:
    # a normal article that merely mentions subscribing must NOT be flagged
    body = "<p>Analysts expect more users to subscribe to the streaming service next year.</p>"
    assert classify_hostile(status_code=200, body=body) is None
