"""Platform feed rules (M7.4, SSOT §6.1 step 3).

Deterministic URL→feed rules for common platforms — no LLM (NFR-7), no network.
Step 3 of feed resolution: tried after a direct feed (M7.2) and HTML autodiscovery
(M7.3), before the homepage-diff fallback (M7.5).

Most rules derive the feed from the URL alone. Two cases need the already-fetched
page HTML (the resolver/scheduler, M7.7, supplies it): a YouTube **handle** (the
`channelId` isn't in the URL) and **WordPress** (detected from the page, then the
`/feed/` convention). Called URL-only, those return None.
"""

from __future__ import annotations

import re
from urllib.parse import SplitResult, urlsplit, urlunsplit

_YT_HOSTS = frozenset({"youtube.com", "m.youtube.com", "youtu.be"})

# A YouTube channelId is "UC" + 22 url-safe chars; anchor it to where pages emit it
# (canonical /channel/ link, og:url, the itemprop meta, or the inline ytInitialData).
_CHANNEL_ID_RE = re.compile(
    r'(?:channel/|"channelId":\s*"|itemprop="channelId"\s+content=")(UC[A-Za-z0-9_-]{22})'
)
_WORDPRESS_RE = re.compile(
    r'name=["\']generator["\'][^>]*content=["\']WordPress|/wp-content/|/wp-json',
    re.IGNORECASE,
)


def _origin(parts: SplitResult) -> str:
    """`scheme://host` for the URL, defaulting to https."""
    return urlunsplit((parts.scheme or "https", parts.netloc, "", "", ""))


def _strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def youtube_channel_id(html: bytes | str) -> str | None:
    """Extract a YouTube channelId from a fetched channel page (for handle/c/user
    URLs whose channelId isn't in the URL). Best-effort; None if not found."""
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    m = _CHANNEL_ID_RE.search(text)
    return m.group(1) if m else None


def _youtube_feed(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def platform_feed(url: str, html: bytes | str | None = None) -> str | None:
    """The platform feed URL for `url`, or None if no rule matches. `html` (the
    page already fetched during resolution) unlocks the YouTube-handle and WordPress
    rules; without it only URL-derivable rules apply."""
    parts = urlsplit(url if "://" in url else "https://" + url)
    host = _strip_www(parts.netloc.lower())
    path = parts.path

    # --- YouTube ---
    if host in _YT_HOSTS:
        channel = re.match(r"/channel/(UC[A-Za-z0-9_-]{22})", path)
        if channel:  # channelId is in the URL → derivable directly
            return _youtube_feed(channel.group(1))
        # /@handle, /c/<name>, /user/<name> → channelId must come from the page. Allow
        # an optional channel-tab suffix (/videos, /streams, …) that operators commonly
        # copy from the channel page.
        if html is not None and re.match(r"/(?:@[^/]+|c/[^/]+|user/[^/]+)(?:/|$)", path):
            cid = youtube_channel_id(html)
            return _youtube_feed(cid) if cid else None
        return None

    # --- Substack: <pub>.substack.com/feed ---
    if host.endswith(".substack.com"):
        return f"https://{host}/feed"

    # --- Medium: medium.com/@user → /feed/@user; <user>.medium.com → /feed ---
    if host == "medium.com":
        user = re.match(r"/(@[^/]+)", path)
        return f"https://medium.com/feed/{user.group(1)}" if user else None
    if host.endswith(".medium.com"):
        return f"https://{host}/feed"

    # --- WordPress: detect from the page, then the /feed/ convention ---
    if html is not None:
        text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
        if _WORDPRESS_RE.search(text):
            return _origin(parts) + "/feed/"

    return None
