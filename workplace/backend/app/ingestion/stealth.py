"""Stealth fetch tier (FR-2 tier 4) — Scrapling's `StealthyFetcher`.

The last HTML tier, reached when a plain fetch and the headless render both
come back blocked, hostile, or empty: an anti-bot interstitial (Cloudflare
Turnstile included), a 403 that only lets real browsers through, or a page that
detects headless Chromium. `StealthyFetcher` drives a patched Chromium with a
real browser fingerprint and solves Cloudflare challenges, then the same
main-content extraction runs over its HTML (`extraction_method="stealth_html"`).

Opt-in: `pip install -e ".[stealth]" && scrapling install`, then
`ENABLE_STEALTH_FETCH=true`. Scrapling is lazy-imported, so importing this
module (and the offline suite) never needs it; tests inject a fake client or a
fake `scrapling.fetchers` module, so a browser is never launched (NFR-3).
"""

from __future__ import annotations

from typing import Any

from app.clients.base import RenderClient, RenderResult
from app.ingestion.fetch_policy import stealth_fetch_kwargs
from app.ingestion.hostile import classify_hostile
from app.ingestion.html_static import extract_main_text


class ScraplingStealthClient:
    """Real stealth client: one `StealthyFetcher.fetch` per URL, returning the
    page HTML in the `RenderClient` shape. Never exercised in tests."""

    def render(self, url: str) -> RenderResult:
        from scrapling.fetchers import StealthyFetcher  # lazy: [stealth] extra

        page: Any = StealthyFetcher.fetch(url, **stealth_fetch_kwargs())
        body: Any = page.body
        html = body.decode(page.encoding or "utf-8", "replace") if isinstance(body, bytes) else body
        return RenderResult(html=str(html), final_url=str(page.url))


def stealth_main_text(url: str, *, stealth_client: RenderClient) -> str | None:
    """Stealth-fetch `url` and extract its main text, or `None` when the page
    is still a wall (challenge, paywall, or login markers) or has no usable
    main content. A wall that survives the stealth browser is not an article."""
    result = stealth_client.render(url)
    if classify_hostile(status_code=200, body=result.html) is not None:
        return None
    return extract_main_text(result.html)
