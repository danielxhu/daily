"""RSS autodiscovery (M7.3, SSOT §6.1 step 2).

Given a page's HTML, find the feeds it advertises via
`<link rel="alternate" type="application/rss+xml|atom+xml|rdf+xml" href="…">`.
Pure parsing, no network: the scheduler (M7.7) fetches the HTML and the direct
parser (M7.2) reads the feed. This is step 2 of feed resolution only — platform
rules (M7.4) and homepage-diff (M7.5) are separate rows.
"""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin

# Feed MIME types advertised in <link type="…">. RSS 2.0, Atom, and RSS 1.0 (RDF) —
# all parseable by M7.2's parse_feed.
_FEED_TYPES = frozenset(
    {
        "application/rss+xml",
        "application/atom+xml",
        "application/rdf+xml",
    }
)


class _FeedLinkParser(HTMLParser):
    """Collects feed `<link rel="alternate" …>` hrefs (and a `<base href>` if any)."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.base_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = {k.lower(): (v or "") for k, v in attrs}
        if tag == "base":
            href = d.get("href", "").strip()
            if href and self.base_href is None:
                self.base_href = href
        elif tag == "link":
            rel = d.get("rel", "").lower().split()
            type_ = d.get("type", "").strip().lower()
            href = d.get("href", "").strip()
            if href and "alternate" in rel and type_ in _FEED_TYPES:
                self.hrefs.append(href)


def discover_feeds(html: bytes | str, *, base_url: str | None = None) -> list[str]:
    """Return the feed URLs advertised by a page, in document order, deduped.

    Relative hrefs are resolved against the page's `<base href>` if present, else
    `base_url`; absolute hrefs are returned unchanged. With neither base available,
    a relative href is returned as-is (best-effort)."""
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    parser = _FeedLinkParser()
    parser.feed(text)
    parser.close()

    base = parser.base_href
    if base and base_url:  # a relative <base href> resolves against the page URL
        base = urljoin(base_url, base)
    base = base or base_url

    out: list[str] = []
    for href in parser.hrefs:
        resolved = urljoin(base, href) if base else href
        if resolved not in out:
            out.append(resolved)
    return out
