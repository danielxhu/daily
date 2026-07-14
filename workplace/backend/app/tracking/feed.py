"""Direct RSS/Atom feed parser (M7.2, SSOT §6.1 step 1).

Parses a **direct feed** — a URL that already serves RSS 2.0 / RSS 1.0 (RDF) /
Atom (§6.1 step 1) — into transient `FeedItem`s. Pure code, no network: the
scheduler fetches (M7.7), and the dedup key + SeenItem set membership are M7.6.
Best-effort — malformed or non-feed XML raises `FeedParseError`; an item missing a
field keeps it as None rather than failing the whole feed.

Safe XML: a DTD declaration is rejected before parsing, so stdlib ElementTree's
expat never expands custom entities (the XXE / billion-laughs vectors on a hostile
feed), and no external resource is ever resolved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET


class FeedParseError(ValueError):
    """Raised when content is not a parseable RSS/Atom feed."""


@dataclass(frozen=True)
class FeedItem:
    """One transient entry parsed from a feed. `guid` / `url` feed the M7.6 dedup
    key; `published` feeds the rolling window (§6.3). NOT a §7 contract type — a feed
    item becomes a SourceRequest before anything is persisted."""

    guid: str | None
    url: str | None
    title: str | None
    summary: str | None
    published: datetime | None


def _local(tag: str) -> str:
    """Local name without the XML namespace (`{ns}tag` → `tag`)."""
    return tag.rsplit("}", 1)[-1]


def _children_by_local(elem: ET.Element) -> dict[str, list[ET.Element]]:
    out: dict[str, list[ET.Element]] = {}
    for child in elem:
        out.setdefault(_local(child.tag), []).append(child)
    return out


def _first_text(children: dict[str, list[ET.Element]], name: str) -> str | None:
    elems = children.get(name)
    if not elems:
        return None
    text = elems[0].text
    return text.strip() if text and text.strip() else None


def _rdf_about(elem: ET.Element) -> str | None:
    """The `rdf:about` URI on an RSS 1.0 `<item>` — its identity (no `<guid>` there)."""
    for key, value in elem.attrib.items():
        if _local(key) == "about" and value:
            return value
    return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:  # RSS pubDate is RFC 822
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        dt = None
    if dt is not None:
        return dt
    try:  # Atom published/updated is RFC 3339 / ISO 8601
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _atom_link(children: dict[str, list[ET.Element]]) -> str | None:
    links = children.get("link", [])
    # prefer rel="alternate" (the canonical entry URL; rel defaults to alternate)
    for link in links:
        if link.get("href") and link.get("rel", "alternate") == "alternate":
            return link.get("href")
    for link in links:  # else the first link carrying an href
        if link.get("href"):
            return link.get("href")
    return None


def _rss_item(elem: ET.Element) -> FeedItem:
    c = _children_by_local(elem)
    return FeedItem(
        # RSS 2.0 has <guid>; RSS 1.0 (RDF) identifies the item by its rdf:about URI
        guid=_first_text(c, "guid") or _rdf_about(elem),
        url=_first_text(c, "link"),
        title=_first_text(c, "title"),
        summary=_first_text(c, "description"),
        published=_parse_date(_first_text(c, "pubDate") or _first_text(c, "date")),
    )


def _atom_entry(elem: ET.Element) -> FeedItem:
    c = _children_by_local(elem)
    return FeedItem(
        guid=_first_text(c, "id"),
        url=_atom_link(c),
        title=_first_text(c, "title"),
        summary=_first_text(c, "summary") or _first_text(c, "content"),
        published=_parse_date(_first_text(c, "published") or _first_text(c, "updated")),
    )


def parse_feed(content: bytes | str) -> list[FeedItem]:
    """Parse a direct RSS/Atom feed into items, in the feed's own order (typically
    newest-first). Raises FeedParseError on malformed or non-feed content."""
    raw = content.encode("utf-8") if isinstance(content, str) else content
    # safe XML: a DTD is where custom entities live (XXE / entity-expansion); refuse
    # it outright. Real feeds never declare one. (Scan the prolog — DTDs precede the
    # root element.)
    if b"<!doctype" in raw[:8192].lower():
        raise FeedParseError("feed declares a DTD; refusing to parse (safe-XML)")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise FeedParseError(f"not well-formed XML: {exc}") from exc

    root_local = _local(root.tag)
    # RSS 1.0's root is <rdf:RDF> (local name uppercase "RDF") — match case-insensitively
    kind = root_local.lower()
    if kind in ("rss", "rdf"):  # RSS 2.0 and RSS 1.0 (RDF)
        return [_rss_item(e) for e in root.iter() if _local(e.tag).lower() == "item"]
    if kind == "feed":  # Atom
        return [_atom_entry(e) for e in root.iter() if _local(e.tag).lower() == "entry"]
    raise FeedParseError(f"not an RSS/Atom feed (root <{root_local}>)")
