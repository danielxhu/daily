"""Homepage-diff fallback (M7.5, SSOT §6.1 step 4 / §6.4).

Last resort when a source has no feed: extract candidate **article** links from a
homepage with heuristics (in-domain, article-like path, exclude nav/footer
boilerplate), then on each poll diff the current link set against the previous one
— new links are new items. Heuristic and best-effort: it can miss or over-detect on
JS-heavy/unusual layouts (must be surfaced in the UI, §6.4); feed-bearing sources
are far more reliable.

Pure functions: no network (M7.7 fetches), no link-set persistence / SeenItem dedup
(M7.6), no ingestion dispatch. This row is extraction + the link-set diff only.
"""

from __future__ import annotations

from collections.abc import Iterable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

# Section/boilerplate path prefixes that are never an individual article.
_BOILERPLATE_PREFIXES = frozenset(
    {
        "tag",
        "tags",
        "category",
        "categories",
        "topic",
        "topics",
        "author",
        "authors",
        "about",
        "contact",
        "privacy",
        "terms",
        "login",
        "signin",
        "signup",
        "register",
        "search",
        "feed",
        "rss",
        "subscribe",
        "page",
        "account",
        "cart",
        "faq",
        "newsletter",
    }
)


def _strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


class _AnchorParser(HTMLParser):
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
        elif tag == "a":
            href = d.get("href", "").strip()
            if href:
                self.hrefs.append(href)


def _is_boilerplate(path: str) -> bool:
    segments = [s for s in path.split("/") if s]
    return bool(segments) and segments[0].lower() in _BOILERPLATE_PREFIXES


def _looks_like_article(path: str) -> bool:
    """A path is article-like if a segment is a slug (hyphenated), a 4+ digit
    year/id, or a numeric id — the common shapes of an article permalink."""
    for seg in (s for s in path.split("/") if s):
        if "-" in seg and len(seg) > 3:
            return True
        if seg.isdigit() and len(seg) >= 4:
            return True
    return False


def extract_candidate_links(html: bytes | str, base_url: str) -> list[str]:
    """Candidate article URLs on a homepage, in document order, deduped. In-domain
    only; nav/footer/section boilerplate and non-article paths are excluded; the
    fragment is dropped (the query is kept). Best-effort — see §6.4."""
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    parser = _AnchorParser()
    parser.feed(text)
    parser.close()

    base = parser.base_href
    if base and base_url:  # a relative <base href> resolves against the page URL
        base = urljoin(base_url, base)
    base = base or base_url
    base_host = _strip_www(urlsplit(base_url).netloc.lower())

    out: list[str] = []
    seen: set[str] = set()
    for href in parser.hrefs:
        absu = urljoin(base, href) if base else href
        parts = urlsplit(absu)
        if parts.scheme not in ("http", "https"):
            continue
        if _strip_www(parts.netloc.lower()) != base_host:  # in-domain only
            continue
        if parts.path in ("", "/"):  # the homepage itself
            continue
        if _is_boilerplate(parts.path) or not _looks_like_article(parts.path):
            continue
        norm = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def diff_new_links(previous: Iterable[str], current: Iterable[str]) -> list[str]:
    """Links in `current` not present in `previous` (new items), in current order."""
    prev = set(previous)
    return [url for url in current if url not in prev]
