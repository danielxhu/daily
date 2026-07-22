"""Per-subscription poll loop (M7.7, SSOT §6.2).

`poll_subscription` runs one subscription's poll: fetch its feed (or homepage),
parse items, drop ones already seen (M7.6 dedup), and dispatch each new item into
the pipeline as a `SourceRequest`. `poll_all` runs every subscription with
**per-subscription isolation** — one failing poll never blocks the others.

Scope: the poll loop + isolation only. Failures are captured in the outcome but
NOT classified/backed-off here — source health + anomaly bookkeeping is M7.8, and
the rolling-window grouping / scoring the dispatched items eventually reach is M7.9.
Fetching is injected (a `fetch` callable) so the loop stays offline-testable.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from urllib.parse import quote, urlsplit

import app.core.config as config
from app.db.subscription_store import list_subscriptions
from app.db.tracked_item_store import upsert_discovered
from app.ingestion.domains import normalize_domain
from app.ingestion.router import is_youtube
from app.schemas.models import SourceRequest, Subscription
from app.tracking.dedup import dedup_key, mark_items_seen, select_new_items
from app.tracking.domain_backoff import blocked_until, is_risk_control, record_risk_control
from app.tracking.feed import FeedItem, FeedParseError, parse_feed
from app.tracking.homepage import extract_candidate_links

# Injected so the loop never touches the network in tests (NFR-3).
Fetch = Callable[[str], bytes]
# Hands a new item to the pipeline; the real dispatcher is wired by M7.9.
Dispatch = Callable[[Subscription, SourceRequest], None]


@dataclass(frozen=True)
class PollOutcome:
    """One subscription's poll result. `error`/`exc` are set (and `ok` False) when
    the fetch/parse failed — isolated here, interpreted into health state by M7.8
    (`exc` is what its classifier inspects; the loop itself never classifies)."""

    subscription_id: str
    ok: bool
    new_count: int
    dispatched: list[str]
    error: str | None = None
    exc: BaseException | None = None
    # M13.4: older items skipped (marked seen, never processed) on a FIRST poll —
    # reported so a capped first check never reads like "the feed only had 5 items"
    backlog_skipped: int = 0
    # M14.5: dispatched URL → dedup key, so the runtime can UN-mark a deferred
    # item (transcription_deferred) and the next poll re-discovers it. The key may
    # be a guid, which is not recoverable from the URL alone — hence carried here.
    dispatched_keys: dict[str, str] = field(default_factory=dict)


def newest_first(items: list[FeedItem]) -> list[FeedItem]:
    """Stable newest-first by `published`, for the first-poll cap (M13.4 review
    blocker): a feed's own order is TYPICALLY newest-first but not guaranteed, and
    the capped backlog is skipped for good — an old→new feed must never get its
    newest items permanently dropped. Python's sort is stable (also under
    reverse=True), so undated items keep their relative feed order and sort after
    dated ones; a fully-undated list (homepage_diff candidates) is unchanged."""
    return sorted(
        items,
        key=lambda i: i.published.timestamp() if i.published else float("-inf"),
        reverse=True,
    )


# owner 2026-07-10 (主流平台兼容): URL shapes that are not plain feeds ----------
#
# Local-first, no paid APIs, no proxies, no login cookies — so support is honest
# per platform: Reddit rides its native RSS; Bilibili/Douyin uploader pages are
# listed via yt-dlp; Weibo profiles use the public mobile JSON endpoint; single
# video/note pages become one-item sources. X/Twitter and Xiaohongshu PROFILES
# have no free, login-less interface — they fail typed with a clear message
# instead of pretending to work.

_SINGLE_VIDEO_HOSTS = ("youtu.be", "b23.tv", "v.douyin.com", "xhslink.com")


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.").removeprefix("m.")


_BVID_RE = re.compile(r"[?&]bvid=(BV[0-9A-Za-z]+)")


def _canonical_video_url(url: str) -> str:
    """A playlist/watch-later PLAYER URL carries the video in `bvid=` (owner
    2026-07-13: 稍后再看 links) — canonicalize to the plain /video/ page, which
    every downstream step (yt-dlp, dedup, the original link) handles."""
    if _host(url) == "bilibili.com":
        m = _BVID_RE.search(url)
        if m:
            return f"https://www.bilibili.com/video/{m.group(1)}/"
    return url


def _is_single_video(url: str) -> bool:
    """A SINGLE video/note page (Bilibili /video/BV… or any player URL carrying
    `bvid=`, YouTube watch/shorts, Douyin video, Xiaohongshu note) added as a
    source: it is one piece of content, not a feed. It becomes a one-item
    source: the item lands once and the seen-set dedups every later poll."""
    parts = urlsplit(url)
    host = _host(url)
    if host in _SINGLE_VIDEO_HOSTS:
        return True
    if host == "bilibili.com" and (parts.path.startswith("/video/") or _BVID_RE.search(url)):
        return True
    if host == "douyin.com" and parts.path.startswith("/video/"):
        return True
    if host == "xiaohongshu.com" and (
        parts.path.startswith("/explore/") or parts.path.startswith("/discovery/item/")
    ):
        return True
    if host.endswith("youtube.com") and (
        parts.path == "/watch" or parts.path.startswith("/shorts/")
    ):
        return True
    return False


def _is_single_content(url: str) -> bool:
    """Single-content pages beyond videos: a Reddit post, a Weibo status."""
    if _is_single_video(url):
        return True
    parts = urlsplit(url)
    host = _host(url)
    if host.endswith("reddit.com") and "/comments/" in parts.path:
        return True
    if host in ("weibo.com", "weibo.cn") and re.fullmatch(r"/\d+/[A-Za-z0-9]+/?", parts.path):
        return True
    if host == "weibo.cn" and parts.path.startswith("/status/"):
        return True
    return False


def _is_bilibili_space(url: str) -> bool:
    """A Bilibili uploader page (space.bilibili.com/<mid>…). The page is a JS
    shell — homepage-diff sees no links in the raw HTML — so it is listed via
    yt-dlp instead (which maintains Bilibili's API signing)."""
    return urlsplit(url).netloc.lower().removeprefix("www.") == "space.bilibili.com"


def _is_douyin_user(url: str) -> bool:
    """A Douyin creator page (douyin.com/user/…) — best-effort via yt-dlp; Douyin
    rate-controls aggressively, so a block is a typed retryable failure."""
    return _host(url) == "douyin.com" and urlsplit(url).path.startswith("/user/")


def _weibo_uid(url: str) -> str | None:
    """The uid of a Weibo PROFILE page (weibo.com/u/<uid>, m.weibo.cn/u/<uid>,
    m.weibo.cn/profile/<uid>, weibo.com/<uid>) — or None."""
    parts = urlsplit(url)
    if _host(url) not in ("weibo.com", "weibo.cn"):
        return None
    m = re.fullmatch(r"/(?:u/|profile/)?(\d{6,})/?", parts.path)
    return m.group(1) if m else None


def _unsupported_platform(url: str) -> str | None:
    """Platforms with no free, login-less interface — an honest typed message
    beats a source that silently never produces anything."""
    host = _host(url)
    if host in ("x.com", "twitter.com"):
        return (
            "X/Twitter has no free public interface (login/paid API only) — "
            "this source cannot be tracked. X/Twitter 无免费公开接口,暂不支持追踪。"
        )
    if host == "xiaohongshu.com" and not _is_single_video(url):
        return (
            "Xiaohongshu profiles require a login session — the profile cannot be "
            "tracked (a single note URL can be added). 小红书主页需要登录态,"
            "暂不支持追踪;单条笔记 URL 可以直接添加。"
        )
    return None


_WEIBO_API = (
    "https://m.weibo.cn/api/container/getIndex?type=uid&value={uid}&containerid=107603{uid}"
)


def _weibo_items(uid: str, fetch: Fetch) -> list[FeedItem]:
    """List a Weibo profile's recent posts via the public mobile JSON endpoint
    (the classic login-less path; goes through the injected `fetch`, so tests
    stay offline). Titles are the post text stripped of HTML, truncated."""
    payload = json.loads(fetch(_WEIBO_API.format(uid=uid)).decode("utf-8", errors="replace"))
    items: list[FeedItem] = []
    for card in (payload.get("data") or {}).get("cards") or []:
        blog = card.get("mblog")
        if not blog:
            continue
        text = re.sub(r"<[^>]+>", "", str(blog.get("text") or "")).strip()
        published = None
        try:
            published = datetime.strptime(str(blog.get("created_at")), "%a %b %d %H:%M:%S %z %Y")
        except (ValueError, TypeError):
            pass
        bid = blog.get("bid") or blog.get("id")
        if not bid:
            continue
        items.append(
            FeedItem(
                guid=str(blog.get("id") or bid),
                url=f"https://m.weibo.cn/status/{bid}",
                title=(text[:120] or None),
                summary=text or None,
                published=published,
            )
        )
    return items


_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# owner 2026-07-13 ("应该按发布日期来而不是按添加日期"): the publish date is on
# the video page we already fetch — Bilibili embeds a unix `pubdate` in its
# initial-state JSON; YouTube/schema.org pages carry a datePublished/uploadDate
# meta. Code-only, zero extra requests.
_PUBLISHED_RES = (
    re.compile(rb'"pubdate"\s*:\s*(\d{9,11})'),
    re.compile(
        rb'itemprop="(?:datePublished|uploadDate)"\s+content="([0-9T:+\-.]+)"', re.IGNORECASE
    ),
    re.compile(
        rb'property="(?:article|og):published_time"\s+content="([0-9T:+\-.]+)"', re.IGNORECASE
    ),
)


def _html_published(content: bytes) -> datetime | None:
    """Best-effort publish date from a fetched page — None when absent."""
    for pattern in _PUBLISHED_RES:
        m = pattern.search(content)
        if not m:
            continue
        raw = m.group(1).decode("ascii", errors="replace")
        try:
            if raw.isdigit():
                return datetime.fromtimestamp(int(raw), tz=UTC)
            return datetime.fromisoformat(raw)
        except (ValueError, OSError):
            continue
    return None


def _html_title(content: bytes) -> str | None:
    """Code-only <title> extraction for a single-video source's item title (video
    pages render the title server-side even when the body is a JS shell)."""
    m = _TITLE_RE.search(content)
    if not m:
        return None
    title = unescape(m.group(1).decode("utf-8", errors="replace")).strip()
    # YouTube's platform suffix — and a bot-check/consent shell page's title is
    # JUST the suffix ("- YouTube"), which must read as "no title", not a title
    # (owner 2026-07-17: an item literally named "- YouTube")
    title = re.sub(r"\s*-\s*YouTube$", "", title).strip()
    return title or None


def _oembed_title(video_url: str, fetch: Callable[[str], bytes]) -> str | None:
    """YouTube's oEmbed endpoint serves the real video title even when the watch
    page answers with a bot-check shell. Code-only, keyless, best-effort."""
    try:
        raw = fetch(
            "https://www.youtube.com/oembed?url=" + quote(video_url, safe="") + "&format=json"
        )
        title = json.loads(raw).get("title")
    except Exception:
        return None
    return str(title).strip() or None if isinstance(title, str) else None


_PLATFORM_LIST_LIMIT = 15


def list_platform_videos(url: str, *, limit: int = _PLATFORM_LIST_LIMIT) -> list[FeedItem]:
    """List an uploader page's latest videos via yt-dlp flat extraction — the
    feed-equivalent for platforms without RSS (Bilibili space). Network-touching;
    tests monkeypatch this symbol. Newest first (extractor order)."""
    import yt_dlp  # lazy: the poll only pays the import when such a source exists

    opts = {"quiet": True, "extract_flat": True, "playlistend": limit, "noprogress": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    items: list[FeedItem] = []
    for entry in (info or {}).get("entries") or []:
        video_url = entry.get("url") or entry.get("webpage_url")
        if not video_url:
            continue
        items.append(
            FeedItem(
                guid=str(entry.get("id")) if entry.get("id") else None,
                url=str(video_url),
                title=str(entry["title"]) if entry.get("title") else None,
                summary=None,
                published=None,
            )
        )
        if len(items) >= limit:
            break
    return _fill_missing_titles(items)


def _fill_missing_titles(items: list[FeedItem]) -> list[FeedItem]:
    """Bilibili's flat listing carries no titles — fetch each video page's
    server-rendered <title> (code-only, one GET per NEW item; the seen-set means
    this runs once per video, not per poll). Best-effort: a failed fetch just
    leaves the title empty rather than failing the source."""
    if all(item.title and item.published for item in items):
        return items
    import httpx

    from app.ingestion.fetch_policy import httpx_client_kwargs

    filled: list[FeedItem] = []
    with httpx.Client(**httpx_client_kwargs()) as client:  # type: ignore[arg-type]
        for item in items:
            title, published = item.title, item.published
            if (not title or published is None) and item.url:
                try:
                    page = client.get(item.url).content
                    title = title or _html_title(page)
                    published = published or _html_published(page)
                except Exception:
                    pass
            filled.append(
                FeedItem(
                    guid=item.guid,
                    url=item.url,
                    title=title,
                    summary=item.summary,
                    published=published,
                )
            )
    return filled


def _fetch_url(sub: Subscription) -> str:
    # Reddit (2026-07-10): subreddits and user pages have NATIVE RSS — rewrite to
    # it so the existing feed pipeline does all the work (applies in every mode;
    # the HTML page would be a JS shell for homepage-diff anyway)
    parts = urlsplit(sub.input_url)
    if _host(sub.input_url).endswith("reddit.com") and re.match(
        r"^/(r|user|u)/[^/]+/?$", parts.path
    ):
        return f"https://www.reddit.com{parts.path.rstrip('/')}/.rss"
    # feed modes poll the resolved feed; homepage-diff polls the homepage itself
    if sub.mode == "homepage_diff":
        return sub.input_url
    return sub.feed_url or sub.input_url


def _items(sub: Subscription, content: bytes) -> list[FeedItem]:
    if sub.mode == "homepage_diff":
        links = extract_candidate_links(content, base_url=sub.input_url)
        return [FeedItem(guid=None, url=u, title=None, summary=None, published=None) for u in links]
    return parse_feed(content)


def poll_subscription(
    conn: sqlite3.Connection,
    sub: Subscription,
    *,
    fetch: Fetch,
    dispatch: Dispatch,
) -> PollOutcome:
    """Poll one subscription. New items are dispatched as URL `SourceRequest`s and
    marked seen; a fetch/parse error is captured (not raised) so callers stay
    isolated. On error nothing is marked seen, so the items retry next poll.

    First poll (M13.4, beta P1-2): a never-polled subscription picks up only the
    latest `FIRST_POLL_ITEM_CAP` items (feeds list newest first); the older backlog
    is marked seen and skipped FOR GOOD — old items are old news, and draining a
    20-item backlog through the pipeline blocks the first check for minutes. The
    skip is reported (`backlog_skipped`), never silent. Later polls are incremental."""
    domain = normalize_domain(sub.input_url)
    # domain frozen by risk control (2026-07-21 audit): polling it again only
    # deepens the block — skip honestly, the freeze lifts on its own clock
    if (until := blocked_until(conn, domain)) is not None:
        return PollOutcome(
            sub.id,
            ok=False,
            new_count=0,
            dispatched=[],
            error=f"domain under risk-control backoff until {until.isoformat(timespec='minutes')}",
        )
    try:
        if (msg := _unsupported_platform(sub.input_url)) is not None:
            raise FeedParseError(msg)
        if _is_bilibili_space(sub.input_url) or _is_douyin_user(sub.input_url):
            # JS-shell creator page → list videos via yt-dlp (B 站/抖音)
            found = list_platform_videos(sub.input_url)
        elif (uid := _weibo_uid(sub.input_url)) is not None:
            # Weibo profile → public mobile JSON endpoint (through injected fetch)
            found = _weibo_items(uid, fetch)
        elif _is_single_content(sub.input_url):
            # one piece of content, not a feed: a one-item source (the page is
            # fetched only for its server-rendered <title>). Playlist/watch-later
            # player URLs canonicalize to the plain /video/ page first.
            video_url = _canonical_video_url(sub.input_url)
            page = fetch(video_url)
            title = _html_title(page)
            if title is None and is_youtube(video_url):
                # the watch page was a bot-check shell — oEmbed still has the title
                title = _oembed_title(video_url, fetch)
            found = [
                FeedItem(
                    guid=None,
                    url=video_url,
                    title=title,
                    summary=None,
                    published=_html_published(page),
                )
            ]
        else:
            found = _items(sub, fetch(_fetch_url(sub)))
        new = select_new_items(conn, sub.id, found)
        picked = new
        if sub.last_polled is None and len(new) > config.FIRST_POLL_ITEM_CAP:
            # "latest N" means BY DATE where the feed provides one — never trust
            # the feed's list order for a permanent skip decision
            picked = newest_first(new)[: config.FIRST_POLL_ITEM_CAP]
        dispatched: list[str] = []
        dispatched_keys: dict[str, str] = {}
        now = datetime.now(UTC)
        for item in picked:
            if item.url:
                dispatch(sub, SourceRequest(kind="url", url=item.url))
                dispatched.append(item.url)
                dispatched_keys[item.url] = dedup_key(item)
                # M15.1a (v0.12 P0): discovery IS the visibility gate — the item
                # exists as knowledge from this moment, whatever the deep pipeline
                # later does to it. A re-discovered (deferred) item resets to new.
                upsert_discovered(
                    conn,
                    subscription_id=sub.id,
                    board_id=sub.board_id,
                    item=item,
                    now=now,
                    module_id=sub.module_id,  # M15.1: item inherits the source's module
                )
        mark_items_seen(conn, sub.id, new)  # ALL new items — the backlog never re-queues
        return PollOutcome(
            sub.id,
            ok=True,
            new_count=len(picked),
            dispatched=dispatched,
            backlog_skipped=len(new) - len(picked),
            dispatched_keys=dispatched_keys,
        )
    except Exception as exc:  # isolation: a broken source must not crash the run
        if is_risk_control(str(exc)):
            record_risk_control(conn, domain, str(exc))
        return PollOutcome(sub.id, ok=False, new_count=0, dispatched=[], error=str(exc), exc=exc)


def poll_all(
    conn: sqlite3.Connection,
    *,
    fetch: Fetch,
    dispatch: Dispatch,
    subscriptions: list[Subscription] | None = None,
) -> list[PollOutcome]:
    """Poll every subscription (or the given list), isolating per-subscription
    failures — one broken source never blocks the rest (FR-2 / §6.6)."""
    subs = subscriptions if subscriptions is not None else list_subscriptions(conn)
    return [poll_subscription(conn, s, fetch=fetch, dispatch=dispatch) for s in subs]
