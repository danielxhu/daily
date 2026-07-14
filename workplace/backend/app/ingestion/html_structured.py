"""HTML structured fallback (M1B.1, SSOT §FR-2 tier 2).

When static extraction (M1A.4 tier 1) comes back empty/too-short, try STRUCTURED
metadata before paying for a headless render (M1B.2 tier 3):

- **JSON-LD `articleBody`** (schema.org Article family) is a full body → `ok`.
- a bare **OpenGraph / meta description** is only a blurb → `partial`, which is
  NOT success: the caller still falls through to render (FR-2).
- nothing usable → `empty`.

These are standardized, stable fields (schema.org / Open Graph Protocol), so we
read them with the stdlib HTML parser — there are no fragile CSS selectors here,
so Scrapling's self-healing `Selector` isn't needed for this tier (it stays a
parser-only option for brittle-DOM cases; its fetchers remain the §2.2 red line
and uninstalled).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Literal


@dataclass(frozen=True)
class StructuredResult:
    text: str | None  # full body when ok; blurb when partial; None when empty
    status: Literal["ok", "partial", "empty"]


class _MetaJsonLdParser(HTMLParser):
    """Collects `<script type="application/ld+json">` blocks and `<meta>` tags.

    HTMLParser puts script/style content into CDATA mode and hands it to
    `handle_data`, so JSON-LD payloads come through intact."""

    def __init__(self) -> None:
        super().__init__()
        self.ldjson_blocks: list[str] = []
        self.meta: dict[str, str] = {}
        self._in_ldjson = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ldjson = True
            self._buf = []
        elif tag == "meta":
            key = a.get("property") or a.get("name")
            if key and "content" in a:
                self.meta.setdefault(key.lower(), a["content"])

    def handle_data(self, data: str) -> None:
        if self._in_ldjson:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_ldjson:
            self._in_ldjson = False
            self.ldjson_blocks.append("".join(self._buf))


# schema.org Article family — only these legitimize an `articleBody` as a body.
# A `Product`/`Recipe`/etc. carrying an `articleBody` key is NOT a tier-2 hit.
_ARTICLE_TYPES = frozenset(
    {
        "article",
        "newsarticle",
        "blogposting",
        "report",
        "techarticle",
        "scholarlyarticle",
        "liveblogposting",
        "analysisnewsarticle",
        "reportagenewsarticle",
        "opinionnewsarticle",
        "reviewnewsarticle",
        "backgroundnewsarticle",
    }
)


def _is_article_type(type_value: Any) -> bool:
    """True if a JSON-LD `@type` (a string or a list of them; bare name or a
    schema.org URL) names an Article-family type."""
    values = type_value if isinstance(type_value, list) else [type_value]
    return any(
        isinstance(v, str) and v.rsplit("/", 1)[-1].lower() in _ARTICLE_TYPES for v in values
    )


def _iter_objects(data: Any) -> Iterator[dict[str, Any]]:
    """Walk a parsed JSON-LD value yielding every dict (handles arrays + @graph)."""
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from _iter_objects(value)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_objects(item)


def _article_body(blocks: list[str]) -> str | None:
    """First non-empty `articleBody` on an Article-family JSON-LD object."""
    for block in blocks:
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue  # malformed JSON-LD is common in the wild — skip, don't crash
        for obj in _iter_objects(data):
            if not _is_article_type(obj.get("@type")):
                continue
            body = obj.get("articleBody")
            if isinstance(body, str) and body.strip():
                return body.strip()
    return None


def extract_structured(html: str) -> StructuredResult:
    """Tier-2 structured extraction. `ok` = a real JSON-LD body; `partial` = only
    an og/meta description blurb; `empty` = nothing usable."""
    parser = _MetaJsonLdParser()
    parser.feed(html)

    # A JSON-LD articleBody is the publisher's EXPLICIT body (schema.org), so it is
    # trusted whenever present — unlike trafilatura's heuristic static text, it is
    # not length-gated (a short but real body still beats paying for a render).
    body = _article_body(parser.ldjson_blocks)
    if body is not None:
        return StructuredResult(text=body, status="ok")

    blurb = parser.meta.get("og:description") or parser.meta.get("description")
    if blurb and blurb.strip():
        return StructuredResult(text=blurb.strip(), status="partial")

    return StructuredResult(text=None, status="empty")
