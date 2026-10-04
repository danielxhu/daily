"""X0.8 — fetch policy: shared client config and typed failure → next action."""

from __future__ import annotations

import typing

import httpx
import pytest

from app.ingestion import fetch_policy as fp
from app.schemas.models import SourceFailureKind


def test_httpx_kwargs_follow_redirects_honour_env_and_have_timeout() -> None:
    kw = fp.httpx_client_kwargs()
    assert kw["follow_redirects"] is True
    assert kw["trust_env"] is True  # HTTP(S)_PROXY/ALL_PROXY from env apply
    assert isinstance(kw["timeout"], (int, float)) and kw["timeout"] > 0
    headers = kw["headers"]
    assert isinstance(headers, dict) and "User-Agent" in headers


def test_httpx_client_adopts_env_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    with httpx.Client(**fp.httpx_client_kwargs()) as client:  # type: ignore[arg-type]
        assert client._trust_env is True


def test_playwright_context_kwargs_disable_downloads() -> None:
    kw = fp.playwright_context_kwargs()
    assert kw["accept_downloads"] is False  # downloads disabled
    assert fp.FETCH_TIMEOUT_MS > 0  # a navigation timeout exists


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


def test_fetch_headers_browser_ua_for_whitelisted_hosts() -> None:
    # hosts that wall the bot UA but serve a browser UA
    for url in (
        "https://mp.weixin.qq.com/s/abc123",
        "https://www.accenture.com/us-en/insights",
        "https://www.mckinsey.com/mgi/x",
        "https://www.bcg.com/publications",
    ):
        h = fp.fetch_headers(url)
        assert h is not None and "Mozilla/5.0" in h["User-Agent"] and "daily" not in h["User-Agent"]
    # everything else keeps the default (client-level bot UA)
    assert fp.fetch_headers("https://www.reuters.com/markets/x") is None
    assert fp.fetch_headers("https://weixin.qq.com/") is None  # host, not prefix-match
