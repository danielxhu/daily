"""FR-2 tier 4 — Scrapling stealth fetch.

`stealth_main_text` runs over the injectable `RenderClient` seam (faked — no
browser, NFR-3). The real `ScraplingStealthClient` is exercised against a FAKE
`scrapling.fetchers` module to assert the kwargs it passes and how it reads the
response. The ingest tests prove where the tier sits in the HTML chain."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from app.clients.base import RenderClient, RenderResult
from app.clients.mock import MockRenderClient
from app.core.config import Settings
from app.ingestion import fetch_policy as fp
from app.ingestion.ingest import ingest_one
from app.ingestion.stealth import ScraplingStealthClient, stealth_main_text
from app.main import _poll_render_fn
from app.schemas.models import SourceRequest
from tests import fixtures_loader as fx

_PARAGRAPH = (
    "The central bank held its policy rate steady on Tuesday and said inflation "
    "had eased faster than expected over the past two quarters, while warning "
    "that services prices remained sticky and wage growth was still elevated. "
)
ARTICLE_HTML = (
    "<html><head><title>Rates held</title></head><body><article><h1>Rates held</h1>"
    + "".join(f"<p>{_PARAGRAPH}</p>" for _ in range(4))
    + "</article></body></html>"
)

_PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")


class _FakeHtmlClient:
    def __init__(self, html: str, status_code: int = 200) -> None:
        self._html = html
        self._status = status_code
        self.calls: list[str] = []

    def get(self, url: str) -> Any:
        self.calls.append(url)
        return SimpleNamespace(
            text=self._html,
            status_code=self._status,
            raise_for_status=lambda: None,
            headers={"content-type": "text/html"},
        )

    def close(self) -> None:
        pass


class _DisconnectClient:
    def get(self, url: str) -> Any:
        raise httpx.RemoteProtocolError("server disconnected")

    def close(self) -> None:
        pass


class _BoomRenderClient:
    def render(self, url: str) -> RenderResult:
        raise TimeoutError("navigation timeout")


# --- fetch policy -------------------------------------------------------------


def test_stealth_kwargs_solve_cloudflare_headless_with_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    kw = fp.stealth_fetch_kwargs()
    assert kw["headless"] is True
    assert kw["solve_cloudflare"] is True
    assert kw["disable_resources"] is True
    assert kw["timeout"] == fp.STEALTH_TIMEOUT_MS > fp.FETCH_TIMEOUT_MS
    assert "proxy" not in kw


def test_stealth_kwargs_pass_the_env_proxy_through(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    assert fp.stealth_fetch_kwargs()["proxy"] == "http://proxy.example:8080"


# --- the real client against a fake scrapling ---------------------------------


def test_scrapling_client_fetches_and_decodes_body(monkeypatch: pytest.MonkeyPatch) -> None:
    rec: dict[str, Any] = {}

    class _StealthyFetcher:
        @classmethod
        def fetch(cls, url: str, **kwargs: Any) -> Any:
            rec["url"], rec["kwargs"] = url, kwargs
            return SimpleNamespace(
                body="<html>页面</html>".encode(), encoding="utf-8", url="https://x.example/final"
            )

    module = ModuleType("scrapling.fetchers")
    module.StealthyFetcher = _StealthyFetcher  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scrapling", ModuleType("scrapling"))
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", module)

    client = ScraplingStealthClient()
    assert isinstance(client, RenderClient)
    result = client.render("https://x.example/a")

    assert result.html == "<html>页面</html>"
    assert result.final_url == "https://x.example/final"
    assert rec["url"] == "https://x.example/a"
    assert rec["kwargs"]["solve_cloudflare"] is True


# --- stealth_main_text ----------------------------------------------------------


def test_stealth_main_text_extracts_a_clean_page() -> None:
    text = stealth_main_text("https://x.example/a", stealth_client=MockRenderClient(ARTICLE_HTML))
    assert text is not None and "policy rate steady" in text


def test_stealth_main_text_rejects_a_surviving_wall() -> None:
    walled = MockRenderClient(fx.load_text("html/cloudflare_challenge.html"))
    assert stealth_main_text("https://x.example/a", stealth_client=walled) is None


# --- position in the ingest chain -------------------------------------------------


def test_anti_bot_page_is_rescued_by_stealth() -> None:
    client = _FakeHtmlClient(fx.load_text("html/cloudflare_challenge.html"))
    stealth = MockRenderClient(ARTICLE_HTML)
    req = SourceRequest(kind="url", url="https://news.example.com/blocked")
    result = ingest_one(req, http_client=cast(httpx.Client, client), stealth_client=stealth)
    assert result.status == "ok"
    assert result.source is not None and result.source.extraction_method == "stealth_html"
    assert stealth.calls == ["https://news.example.com/blocked"]


def test_a_wall_that_survives_stealth_stays_typed() -> None:
    client = _FakeHtmlClient(fx.load_text("html/cloudflare_challenge.html"))
    stealth = MockRenderClient(fx.load_text("html/cloudflare_challenge.html"))
    req = SourceRequest(kind="url", url="https://news.example.com/blocked")
    result = ingest_one(req, http_client=cast(httpx.Client, client), stealth_client=stealth)
    assert result.status == "failed"
    assert result.failure is not None and result.failure.kind == "anti_bot"


def test_paywall_page_gets_a_stealth_try() -> None:
    client = _FakeHtmlClient(fx.load_text("html/paywall_bloomberg.html"))
    req = SourceRequest(kind="url", url="https://markets.example.com/story")
    result = ingest_one(
        req,
        http_client=cast(httpx.Client, client),
        render_client=MockRenderClient(ARTICLE_HTML),
        stealth_client=MockRenderClient(ARTICLE_HTML),
    )
    assert result.status == "ok"
    assert result.source is not None and result.source.extraction_method == "stealth_html"


def test_transport_failure_falls_through_render_to_stealth() -> None:
    req = SourceRequest(kind="url", url="https://firm.example.com/insights/x")
    result = ingest_one(
        req,
        http_client=cast(httpx.Client, _DisconnectClient()),
        render_client=_BoomRenderClient(),
        stealth_client=MockRenderClient(ARTICLE_HTML),
    )
    assert result.status == "ok"
    assert result.source is not None and result.source.extraction_method == "stealth_html"


def test_empty_render_falls_through_to_stealth() -> None:
    client = _FakeHtmlClient(fx.load_text("html/empty_body.html"))
    req = SourceRequest(kind="url", url="https://spa.example.com/x")
    result = ingest_one(
        req,
        http_client=cast(httpx.Client, client),
        render_client=MockRenderClient(fx.load_text("html/empty_body.html")),
        stealth_client=MockRenderClient(ARTICLE_HTML),
    )
    assert result.status == "ok"
    assert result.source is not None and result.source.extraction_method == "stealth_html"


def test_stealth_tier_is_off_by_default() -> None:
    client = _FakeHtmlClient(fx.load_text("html/cloudflare_challenge.html"))
    req = SourceRequest(kind="url", url="https://news.example.com/blocked")
    result = ingest_one(req, http_client=cast(httpx.Client, client))
    assert result.failure is not None and result.failure.kind == "anti_bot"


# --- poll-side browser callable ---------------------------------------------------


def test_poll_render_fn_is_none_when_no_browser_tier_enabled() -> None:
    assert _poll_render_fn(Settings(_env_file=None)) is None  # type: ignore[call-arg]


def test_poll_render_fn_falls_back_from_render_to_stealth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingestion import html_render, stealth

    def boom(self: Any, url: str) -> RenderResult:
        raise TimeoutError("render timed out")

    def stealthy(self: Any, url: str) -> RenderResult:
        return RenderResult(html="<html>stealth</html>", final_url=url)

    monkeypatch.setattr(html_render.PlaywrightRenderClient, "render", boom)
    monkeypatch.setattr(stealth.ScraplingStealthClient, "render", stealthy)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, enable_html_render=True, enable_stealth_fetch=True
    )
    fn = _poll_render_fn(settings)
    assert fn is not None and fn("https://x.example/list") == "<html>stealth</html>"
