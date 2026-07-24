"""X0.8 — fetch policy guard: the red lines hold by construction."""

from __future__ import annotations

import typing
from pathlib import Path

import httpx
import pytest

from app.ingestion import fetch_policy as fp
from app.schemas.models import SourceFailureKind

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_policy_switches_all_off() -> None:
    assert fp.ALLOW_COOKIES is False
    assert fp.ALLOW_PROXY is False
    assert fp.ALLOW_ARCHIVE_BYPASS is False
    assert fp.ALLOW_LOGIN is False


def test_httpx_kwargs_carry_no_cookies_or_proxy_and_have_timeout() -> None:
    kw = fp.httpx_client_kwargs()
    assert "cookies" not in kw and "proxy" not in kw and "proxies" not in kw
    assert kw["follow_redirects"] is True
    assert kw["trust_env"] is False  # don't read HTTP(S)_PROXY/ALL_PROXY from env
    assert isinstance(kw["timeout"], (int, float)) and kw["timeout"] > 0
    headers = kw["headers"]
    assert isinstance(headers, dict) and "User-Agent" in headers


def test_httpx_client_ignores_env_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even with a proxy set in the environment, the policy client must not adopt it.
    monkeypatch.setenv("HTTPS_PROXY", "http://evil.proxy:8080")
    monkeypatch.setenv("ALL_PROXY", "http://evil.proxy:8080")
    with httpx.Client(**fp.httpx_client_kwargs()) as client:  # type: ignore[arg-type]
        assert client._trust_env is False


def test_playwright_context_kwargs_are_safe() -> None:
    kw = fp.playwright_context_kwargs()
    assert kw["accept_downloads"] is False  # downloads disabled
    assert "storage_state" not in kw  # no cookies/session
    assert "proxy" not in kw  # no proxy
    assert fp.FETCH_TIMEOUT_MS > 0  # a navigation timeout exists


# --- CASR guard (FR-16) -----------------------------------------------------


def test_casr_allows_whitelisted_claim_anchored() -> None:
    fp.assert_casr_allowed(domain="www.sec.gov", claim_anchored=True)
    fp.assert_casr_allowed(domain="efts.sec.gov", claim_anchored=True)  # subdomain
    assert fp.casr_domain_allowed("federalreserve.gov") is True


def test_casr_rejects_offwhitelist_domain() -> None:
    assert fp.casr_domain_allowed("example.com") is False
    with pytest.raises(fp.FetchPolicyError):
        fp.assert_casr_allowed(domain="example.com", claim_anchored=True)


def test_casr_rejects_topic_browsing() -> None:
    # whitelisted host but NOT claim-anchored → still forbidden (never browse)
    with pytest.raises(fp.FetchPolicyError):
        fp.assert_casr_allowed(domain="sec.gov", claim_anchored=False)


# --- typed failure → next action (§6.6 / FR-2) ------------------------------


def test_every_source_failure_kind_has_a_next_action() -> None:
    kinds = set(typing.get_args(SourceFailureKind))
    assert kinds == set(fp.NEXT_ACTION)
    assert all(fp.NEXT_ACTION[k] for k in kinds)  # non-empty


def test_next_action_mapping_matches_ssot_6_6() -> None:
    for k in ("paywall", "login_required", "anti_bot"):
        assert "paste" in fp.next_action_for(k).lower()
    assert "scanned" in fp.next_action_for("unsupported_file").lower()
    assert fp.next_action_for("timeout") == "Retry."


def test_typed_skip_builds_failure_with_next_action() -> None:
    f = fp.typed_skip(
        "paywall",
        reason="Paywalled; not fetched.",
        requested_url="https://paywall.example/x",
        source_type="webpage",
    )
    assert f.kind == "paywall"
    assert f.next_action and "paste" in f.next_action.lower()
    assert f.requested_url == "https://paywall.example/x"


# --- Scrapling parser-only: no stealth fetchers in the dependency manifest ---


def test_no_scrapling_fetchers_or_stealth_in_manifest() -> None:
    pyproject = (BACKEND_DIR / "pyproject.toml").read_text(encoding="utf-8")
    assert "scrapling[fetchers]" not in pyproject
    assert "StealthyFetcher" not in pyproject


def test_no_stealth_fetcher_imported_or_instantiated_in_app_code() -> None:
    # The policy module legitimately *names* StealthyFetcher in prose to forbid
    # it, and parser-only `from scrapling import Selector` is ALLOWED (§10). So we
    # only flag the actual fetcher/stealth APIs, not any scrapling import.
    bad_patterns = (
        "import StealthyFetcher",
        "StealthyFetcher(",
        "scrapling.fetchers",
        "from scrapling.fetchers",
        "scrapling install",
    )
    offenders = []
    for p in (BACKEND_DIR / "app").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if any(pat in text for pat in bad_patterns):
            offenders.append(p.name)
    assert offenders == []


def test_fetch_headers_browser_ua_for_wechat_only() -> None:
    # owner 2026-07-24: mp.weixin walls the bot UA but serves the full
    # server-rendered article to a plain browser UA — a static UA string,
    # no cookies/captcha (same stance the yt-dlp video path already takes)
    wx = fp.fetch_headers("https://mp.weixin.qq.com/s/abc123")
    assert wx is not None and "Mozilla/5.0" in wx["User-Agent"]
    assert "daily" not in wx["User-Agent"]
    # everything else keeps the honest default (client-level bot UA)
    assert fp.fetch_headers("https://www.reuters.com/markets/x") is None
    assert fp.fetch_headers("https://weixin.qq.com/") is None  # host, not prefix-match
