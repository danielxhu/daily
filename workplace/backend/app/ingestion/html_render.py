"""Headless-render fallback (M1B.2, SSOT §FR-2 tier 3).

Last resort for JS-only pages: when static (M1A.4) is empty AND structured
(M1B.1) is not `ok` (i.e. empty OR only a `partial` blurb), render the page with
Playwright and run the same main-content extraction over the rendered DOM
(`extraction_method="rendered_html"`).

Strictly bounded by the X0.8 fetch policy (§2.2): an **isolated context with NO
user cookies/session**, **downloads disabled**, and a **navigation timeout**. We
do NOT bypass paywalls/login/anti-bot — a render failure is a typed skip, never a
workaround. Playwright is lazy-imported so importing this module (and the offline
suite) never needs the browser; the `RenderClient` seam is mocked in tests, so a
browser is never launched (NFR-3).
"""

from __future__ import annotations

from typing import Any

from app.clients.base import RenderClient, RenderResult
from app.ingestion.fetch_policy import FETCH_TIMEOUT_MS, playwright_context_kwargs
from app.ingestion.html_static import extract_main_text


class PlaywrightRenderClient:
    """Real `RenderClient`: headless Chromium, isolated + cookie-less context,
    downloads off, timeout-bounded. Never exercised in tests."""

    def render(self, url: str) -> RenderResult:
        from playwright.sync_api import sync_playwright  # lazy: heavy + bundles a browser

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(**playwright_context_kwargs())
                context.set_default_navigation_timeout(FETCH_TIMEOUT_MS)
                page = context.new_page()
                page.goto(url)
                html: Any = page.content()
                final_url: Any = page.url
            finally:
                browser.close()
        return RenderResult(html=html, final_url=final_url)


def render_main_text(url: str, *, render_client: RenderClient) -> str | None:
    """Render `url` and extract main text from the rendered DOM, or `None` if the
    rendered page still has no usable main content."""
    result = render_client.render(url)
    return extract_main_text(result.html)
