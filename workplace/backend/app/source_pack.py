"""Built-in default source-pack template (FR-3).

A fixed, editable starter list of seed sources — central bank / regulator /
company IR / a few finance RSS + a YouTube channel — that seeds a board's
subscriptions on cold start, so day one isn't empty. The operator trims/edits
this pack, then subscribes (the tracking machinery is Stage 7).

This is deliberately **NOT** topic-wide web discovery (§2.2): it is a static
starter list, never a search for "all sources about X".
"""

from __future__ import annotations

from app.schemas.models import SourcePackEntry

# Real, well-known sources. URLs are defaults the operator edits; nothing here is
# fetched in this stage. M12.1: each entry is tagged with a preset topic board
# (政治 b_politics / 经济 b_economy / 科技 b_tech) so the Sources view can offer
# per-board recommendations — still a fixed curated list, never topic discovery.
DEFAULT_SOURCE_PACK: tuple[SourcePackEntry, ...] = (
    # --- 经济 (economy / markets) ---
    SourcePackEntry(
        label="Federal Reserve — press releases",
        url="https://www.federalreserve.gov/feeds/press_all.xml",
        mode="direct",
        category="central_bank",
        board_id="b_economy",
    ),
    SourcePackEntry(
        label="SEC — press releases",
        url="https://www.sec.gov/news/pressreleases.rss",
        mode="direct",
        category="regulator",
        board_id="b_economy",
    ),
    SourcePackEntry(
        label="WSJ — markets",
        url="https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        mode="direct",
        category="rss",
        board_id="b_economy",
    ),
    SourcePackEntry(
        label="CNBC — economy",
        url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
        mode="direct",
        category="rss",
        board_id="b_economy",
    ),
    SourcePackEntry(
        label="Yahoo Finance — YouTube",
        url="https://www.youtube.com/@YahooFinance",
        mode="platform",
        category="youtube",
        board_id="b_economy",
    ),
    # --- 政治 (politics / world affairs) ---
    SourcePackEntry(
        label="BBC — world news",
        url="https://feeds.bbci.co.uk/news/world/rss.xml",
        mode="direct",
        category="rss",
        board_id="b_politics",
    ),
    SourcePackEntry(
        label="Politico — politics",
        url="https://rss.politico.com/politics-news.xml",
        mode="direct",
        category="rss",
        board_id="b_politics",
    ),
    SourcePackEntry(
        label="The Guardian — world",
        url="https://www.theguardian.com/world/rss",
        mode="direct",
        category="rss",
        board_id="b_politics",
    ),
    # --- 科技 (tech) ---
    SourcePackEntry(
        label="NVIDIA — investor relations",
        url="https://investor.nvidia.com/",
        mode="homepage_diff",
        category="company_ir",
        board_id="b_tech",
    ),
    SourcePackEntry(
        label="Apple — investor relations",
        url="https://investor.apple.com/",
        mode="homepage_diff",
        category="company_ir",
        board_id="b_tech",
    ),
    SourcePackEntry(
        label="TechCrunch",
        url="https://techcrunch.com/feed/",
        mode="direct",
        category="rss",
        board_id="b_tech",
    ),
    SourcePackEntry(
        label="Hacker News — front page",
        url="https://news.ycombinator.com/rss",
        mode="direct",
        category="rss",
        board_id="b_tech",
    ),
    SourcePackEntry(
        label="36氪",
        url="https://36kr.com/feed",
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
