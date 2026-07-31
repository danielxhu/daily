"""Built-in default source-pack template (FR-3).

A fixed, editable starter list of seed sources — research houses and a couple of
technology shows — that seeds a board's subscriptions on cold start, so day one
isn't empty. Every entry is a source that survives a real poll on default
settings: a feed where one exists, otherwise a listing page the discovery chain
can recover with a plain fetch. Sources that answer only to a headless browser
are deliberately left out — the render fallback is off by default, so they would
seed a typed failure on day one. The operator trims or edits their copy.

This is deliberately **NOT** topic-wide web discovery (§2.2): it is a static
starter list, never a search for "all sources about X".
"""

from __future__ import annotations

from app.schemas.models import SourcePackEntry

# Real, well-known sources. URLs are defaults the operator edits. Each entry is
# tagged with a preset topic board (政治 b_politics / 经济 b_economy / 科技 b_tech)
# so the Sources view can offer per-board recommendations — still a fixed curated
# list, never topic discovery.
DEFAULT_SOURCE_PACK: tuple[SourcePackEntry, ...] = (
    # --- 经济 (research houses: long-form insight, published on a slow cadence) ---
    SourcePackEntry(
        label="McKinsey — insights",
        url="https://www.mckinsey.com/insights/rss",
        mode="direct",
        category="rss",
        board_id="b_economy",
    ),
    SourcePackEntry(
        label="Roland Berger — insights",
        url="https://www.rolandberger.com/en/Insights/",
        mode="direct",
        category="rss",
        board_id="b_economy",
    ),
    # --- 科技 (a newsletter with a real feed, and a podcast show page) ---
    SourcePackEntry(
        label="Latent Space",
        url="https://www.latent.space/feed",
        mode="direct",
        category="rss",
        board_id="b_tech",
    ),
    SourcePackEntry(
        label="小宇宙 · 硬地骇客",
        url="https://www.xiaoyuzhoufm.com/podcast/60502e253c92d4f62c2a9577",
        mode="direct",
        category="rss",
        board_id="b_tech",
    ),
)


def default_source_pack() -> list[SourcePackEntry]:
    """A fresh, independent copy of the built-in default pack — the operator edits
    their copy, never the shared constant. Each entry is deep-copied because
    `SourcePackEntry` is not frozen, so a shallow `list(...)` would hand back the
    same objects and an edit (e.g. a URL change) would pollute the template."""
    return [entry.model_copy(deep=True) for entry in DEFAULT_SOURCE_PACK]
