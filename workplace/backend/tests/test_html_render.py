"""M1B.2 — headless-render fallback (tier 3).

`render_main_text` extracts the rendered DOM's main content via the injectable
`RenderClient` seam (mocked — no browser, NFR-3). The real `PlaywrightRenderClient`
is exercised against a FAKE playwright module to assert the X0.8 guardrails:
isolated cookie-less context, downloads disabled, a navigation timeout, headless,
and the browser is always closed."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from app.clients.base import RenderClient
from app.clients.mock import MockRenderClient
from app.ingestion.fetch_policy import FETCH_TIMEOUT_MS, playwright_context_kwargs
from app.ingestion.html_render import PlaywrightRenderClient, render_main_text
from tests import fixtures_loader as fx


def test_mock_render_client_satisfies_protocol() -> None:
    assert isinstance(MockRenderClient(), RenderClient)


def test_render_main_text_extracts_from_rendered_dom() -> None:
    rc = MockRenderClient(fx.load_text("html/static_article.html"))
    text = render_main_text("https://spa.example/x", render_client=rc)
    assert text is not None and "$30.8B" in text
    assert rc.calls == ["https://spa.example/x"]


def test_render_main_text_none_when_rendered_dom_empty() -> None:
    rc = MockRenderClient(fx.load_text("html/empty_body.html"))
    assert render_main_text("https://spa.example/x", render_client=rc) is None


# --- real PlaywrightRenderClient against a fake playwright (no browser) ---------


def _install_fake_playwright(monkeypatch: pytest.MonkeyPatch, rec: dict[str, Any]) -> None:
    def launch(**kwargs: Any) -> Any:
        rec["launch"] = kwargs

        def new_context(**ctx_kwargs: Any) -> Any:
            rec["context"] = ctx_kwargs
            page = SimpleNamespace(
                goto=lambda u: rec.__setitem__("goto", u),
                content=lambda: "<html><body><article>rendered body</article></body></html>",
                url="https://spa.example/final",
            )
            return SimpleNamespace(
                set_default_navigation_timeout=lambda ms: rec.__setitem__("timeout", ms),
                new_page=lambda: page,
            )

        return SimpleNamespace(
            new_context=new_context,
            close=lambda: rec.__setitem__("closed", True),
        )

    chromium = SimpleNamespace(launch=launch)

    class _CM:  # context-manager dunders must live on the type, not an instance
        def __enter__(self) -> Any:
            return SimpleNamespace(chromium=chromium)

        def __exit__(self, *a: Any) -> None:
            return None

    module = ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: _CM()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)


def test_playwright_client_obeys_fetch_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    rec: dict[str, Any] = {}
    _install_fake_playwright(monkeypatch, rec)

    result = PlaywrightRenderClient().render("https://spa.example/x")

    assert result.html == "<html><body><article>rendered body</article></body></html>"
    assert result.final_url == "https://spa.example/final"
    assert rec["launch"] == {"headless": True}
    assert rec["context"] == playwright_context_kwargs()  # no cookies, downloads off, no proxy
    assert rec["context"]["accept_downloads"] is False
    assert "storage_state" not in rec["context"] and "proxy" not in rec["context"]
    assert rec["timeout"] == FETCH_TIMEOUT_MS  # navigation timeout set
    assert rec["closed"] is True  # browser always closed
