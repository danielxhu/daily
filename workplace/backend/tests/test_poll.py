"""M7.7 — poll scheduler + per-subscription poll loop (SSOT §6.2 / §6.6).

`poll_subscription` fetches → parses → dedups (M7.6) → dispatches new items as URL
SourceRequests; `poll_all` isolates per-subscription failures. The scheduler wires
one interval job per subscription. Scope: poll loop + isolation + scheduling only —
no health/anomaly bookkeeping (M7.8), no rolling-window/scoring (M7.9). Fetch and
dispatch are injected; the scheduler backend is faked (no real APScheduler)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db.engine import init_db
from app.db.subscription_store import create_subscription
from app.schemas.models import SourceRequest, Subscription
from app.tracking.poll import poll_all, poll_subscription
from app.tracking.scheduler import PollScheduler
from tests.fixtures_loader import fixture_path


def _rss() -> bytes:
    return fixture_path("feeds/rss_sample.xml").read_bytes()


def _homepage() -> bytes:
    return fixture_path("feeds/homepage_t0.html").read_bytes()


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, SourceRequest]] = []

    def __call__(self, sub: Subscription, req: SourceRequest) -> None:
        self.calls.append((sub.id, req))


# --- poll loop -------------------------------------------------------------


def test_direct_feed_poll_dispatches_new_items_then_dedups(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(
        conn,
        input_url="https://www.sec.gov/news/pressreleases",
        mode="direct",
        feed_url="https://www.sec.gov/news/pressreleases.rss",
    )
    rec = _Recorder()
    out = poll_subscription(conn, sub, fetch=lambda _url: _rss(), dispatch=rec)
    assert out.ok and out.new_count == 3
    # each new feed item becomes a URL SourceRequest into the pipeline
    assert [r.url for _id, r in rec.calls] == [
        "https://www.sec.gov/news/press-release/2026-101",
        "https://www.sec.gov/news/press-release/2026-100",
        "https://www.sec.gov/news/statement/market-structure-2026",
    ]
    assert all(r.kind == "url" for _id, r in rec.calls)

    # a second poll of the same feed dispatches nothing (seen-set dedup)
    rec2 = _Recorder()
    out2 = poll_subscription(conn, sub, fetch=lambda _url: _rss(), dispatch=rec2)
    assert out2.ok and out2.new_count == 0 and rec2.calls == []


def test_homepage_diff_poll_dispatches_article_links(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(conn, input_url="https://news.example.com/", mode="homepage_diff")
    rec = _Recorder()
    out = poll_subscription(conn, sub, fetch=lambda _url: _homepage(), dispatch=rec)
    assert out.ok
    assert [r.url for _id, r in rec.calls] == [
        "https://news.example.com/2026/06/fed-holds-rates-steady",
        "https://news.example.com/2026/06/nvidia-tops-q2-estimates",
    ]


def test_homepage_diff_polls_the_homepage_not_a_feed_url(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(conn, input_url="https://news.example.com/", mode="homepage_diff")
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return _homepage()

    poll_subscription(conn, sub, fetch=fetch, dispatch=_Recorder())
    assert fetched == ["https://news.example.com/"]


def test_fetch_failure_is_isolated_and_retries_next_poll(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(
        conn, input_url="https://x/feed", mode="direct", feed_url="https://x/feed"
    )

    def boom(_url: str) -> bytes:
        raise ConnectionError("down")

    out = poll_subscription(conn, sub, fetch=boom, dispatch=_Recorder())
    assert out.ok is False and out.new_count == 0 and "down" in (out.error or "")

    # nothing was marked seen on failure → a later successful poll still emits items
    rec = _Recorder()
    ok = poll_subscription(conn, sub, fetch=lambda _url: _rss(), dispatch=rec)
    assert ok.ok and ok.new_count == 3


def test_poll_all_isolates_one_failing_subscription(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    bad = create_subscription(
        conn, input_url="https://bad/feed", mode="direct", feed_url="https://bad/feed"
    )
    good = create_subscription(
        conn, input_url="https://good/feed", mode="direct", feed_url="https://good/feed"
    )

    def fetch(url: str) -> bytes:
        if "bad" in url:
            raise TimeoutError("nope")
        return _rss()

    rec = _Recorder()
    outcomes = {o.subscription_id: o for o in poll_all(conn, fetch=fetch, dispatch=rec)}
    assert outcomes[bad.id].ok is False  # the broken source failed …
    assert outcomes[good.id].ok is True and outcomes[good.id].new_count == 3  # … good one still ran
    assert all(sid == good.id for sid, _req in rec.calls)


# --- scheduler -------------------------------------------------------------


class _FakeBackend:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self.started = False
        self.stopped = False

    def add_job(self, func: Any, trigger: str, **kwargs: Any) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def start(self) -> None:
        self.started = True

    def shutdown(self) -> None:
        self.stopped = True


def test_scheduler_registers_one_recurring_tick() -> None:
    # M9.10: a single recurring tick (not one job per subscription) — each tick
    # re-reads the current subscriptions, so adds/removes after startup are handled.
    backend = _FakeBackend()
    scheduler = PollScheduler(backend=backend)
    ticks: list[int] = []
    scheduler.schedule_tick(lambda: ticks.append(1), minutes=5)

    assert [j["trigger"] for j in backend.jobs] == ["interval"]
    assert backend.jobs[0]["minutes"] == 5
    assert backend.jobs[0]["id"] == "poll:tick" and backend.jobs[0]["replace_existing"]
    # the registered job IS the tick action
    backend.jobs[0]["func"]()
    assert ticks == [1]

    scheduler.start()
    scheduler.shutdown()
    assert backend.started and backend.stopped


# --- M13.4 (beta P1-2): first poll is capped to the latest items -----------------


def test_first_poll_caps_to_the_latest_items_and_skips_the_backlog_for_good(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A never-polled source picks up only the newest N items; the older backlog is
    marked seen and never re-queues — Day-1 must not drain a whole feed through the
    pipeline synchronously. The skip is reported, never silent."""
    monkeypatch.setattr("app.core.config.FIRST_POLL_ITEM_CAP", 2)
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(
        conn,
        input_url="https://www.sec.gov/news/pressreleases",
        mode="direct",
        feed_url="https://www.sec.gov/news/pressreleases.rss",
    )
    assert sub.last_polled is None  # never polled → the cap applies

    rec = _Recorder()
    out = poll_subscription(conn, sub, fetch=lambda _url: _rss(), dispatch=rec)
    # the newest 2 of 3 items dispatch (feeds list newest first); the skip is reported
    assert out.ok and out.new_count == 2 and out.backlog_skipped == 1
    assert [r.url for _id, r in rec.calls] == [
        "https://www.sec.gov/news/press-release/2026-101",
        "https://www.sec.gov/news/press-release/2026-100",
    ]

    # the skipped backlog item was marked seen too: a re-poll dispatches NOTHING —
    # the backlog never drips back in, later polls are genuinely incremental
    rec2 = _Recorder()
    out2 = poll_subscription(conn, sub, fetch=lambda _url: _rss(), dispatch=rec2)
    assert out2.new_count == 0 and out2.backlog_skipped == 0 and rec2.calls == []


def test_later_polls_are_not_capped(tmp_path: Path, monkeypatch: Any) -> None:
    """The cap is a FIRST-poll cold-start guard only: once a subscription has a
    last_polled, every genuinely-new item flows through uncapped."""
    monkeypatch.setattr("app.core.config.FIRST_POLL_ITEM_CAP", 2)
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(
        conn,
        input_url="https://www.sec.gov/news/pressreleases",
        mode="direct",
        feed_url="https://www.sec.gov/news/pressreleases.rss",
    )
    polled = sub.model_copy(  # an already-polled source
        update={"last_polled": datetime(2026, 7, 1, tzinfo=UTC)}
    )
    rec = _Recorder()
    out = poll_subscription(conn, polled, fetch=lambda _url: _rss(), dispatch=rec)
    assert out.ok and out.new_count == 3 and out.backlog_skipped == 0
    assert len(rec.calls) == 3


OLD_TO_NEW_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><link>https://ex.com/old</link><pubDate>Tue, 01 Jul 2026 00:00:00 GMT</pubDate></item>
<item><link>https://ex.com/mid</link><pubDate>Wed, 02 Jul 2026 00:00:00 GMT</pubDate></item>
<item><link>https://ex.com/new</link><pubDate>Thu, 03 Jul 2026 00:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_first_poll_cap_takes_latest_by_date_not_feed_order(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """M13.4 review blocker: a feed's own order is not guaranteed newest-first. On
    an old→new feed the cap must still pick the newest BY DATE — the permanent
    backlog skip must never drop the newest items."""
    monkeypatch.setattr("app.core.config.FIRST_POLL_ITEM_CAP", 2)
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(
        conn, input_url="https://ex.com/", mode="direct", feed_url="https://ex.com/feed"
    )
    rec = _Recorder()
    out = poll_subscription(conn, sub, fetch=lambda _url: OLD_TO_NEW_RSS, dispatch=rec)
    # newest two by pubDate — NOT the first two in feed order
    assert [r.url for _id, r in rec.calls] == ["https://ex.com/new", "https://ex.com/mid"]
    assert out.new_count == 2 and out.backlog_skipped == 1
    # the skipped OLD item stays skipped (seen) — it never drips back in
    rec2 = _Recorder()
    out2 = poll_subscription(conn, sub, fetch=lambda _url: OLD_TO_NEW_RSS, dispatch=rec2)
    assert out2.new_count == 0 and rec2.calls == []


# --- 2026-07-10 (owner: B 站兼容): non-feed URL shapes -----------------------------


def _collect_dispatch() -> tuple[list[str], Any]:
    urls: list[str] = []

    def dispatch(sub: Subscription, req: SourceRequest) -> None:
        urls.append(req.url or "")

    return urls, dispatch


def test_a_single_video_url_becomes_a_one_item_source(tmp_path: Path) -> None:
    """A Bilibili/YouTube VIDEO page added as a source is one piece of content,
    not a feed: it lands once (title from the server-rendered <title>), and the
    seen-set dedups every later poll — no XML parse, no DTD error."""
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(
        conn,
        input_url="https://www.bilibili.com/video/BV14eRcBnEpE/?spm_id_from=x",
        mode="platform",
    )
    page = (
        "<html><head><title>【测试】某视频标题_哔哩哔哩</title></head>"
        '<body><script>window.__INITIAL_STATE__={"videoData":{"pubdate":1782864000}}</script>'
        "</body></html>"
    )
    urls, dispatch = _collect_dispatch()

    out = poll_subscription(conn, sub, fetch=lambda _u: page.encode(), dispatch=dispatch)
    assert out.ok and out.new_count == 1
    assert urls == ["https://www.bilibili.com/video/BV14eRcBnEpE/?spm_id_from=x"]
    row = conn.execute("SELECT title, published FROM tracked_items").fetchone()
    assert row["title"] == "【测试】某视频标题_哔哩哔哩"
    # owner 2026-07-13: the item carries the video's PUBLISH date (embedded
    # `pubdate`), never the date the user happened to add it
    assert row["published"] is not None and row["published"].startswith("2026-07-01")

    again = poll_subscription(conn, sub, fetch=lambda _u: page.encode(), dispatch=dispatch)
    assert again.ok and again.new_count == 0  # dedup: the one item never repeats


def test_a_bilibili_space_lists_videos_via_ytdlp(tmp_path: Path, monkeypatch: Any) -> None:
    """A Bilibili uploader page is a JS shell (homepage-diff sees nothing) — the
    poll lists its latest videos via yt-dlp instead. The lister is injected here;
    the real one is exercised only against the live site."""
    from app.tracking import poll as poll_mod
    from app.tracking.feed import FeedItem

    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(
        conn, input_url="https://space.bilibili.com/2104838515/?spm=x", mode="homepage_diff"
    )
    monkeypatch.setattr(
        poll_mod,
        "list_platform_videos",
        lambda _url, **_kw: [
            FeedItem(
                guid="BV1xx",
                url="https://www.bilibili.com/video/BV1xx/",
                title="视频一",
                summary=None,
                published=None,
            ),
            FeedItem(
                guid="BV2yy",
                url="https://www.bilibili.com/video/BV2yy/",
                title="视频二",
                summary=None,
                published=None,
            ),
        ],
    )
    urls, dispatch = _collect_dispatch()

    def boom(_u: str) -> bytes:
        raise AssertionError("fetch must not be called")

    out = poll_subscription(conn, sub, fetch=boom, dispatch=dispatch)
    assert out.ok and out.new_count == 2
    assert urls == [
        "https://www.bilibili.com/video/BV1xx/",
        "https://www.bilibili.com/video/BV2yy/",
    ]
    titles = {r["title"] for r in conn.execute("SELECT title FROM tracked_items").fetchall()}
    assert titles == {"视频一", "视频二"}


# --- 2026-07-10 (owner: 主流平台兼容): Reddit / Weibo / Douyin / X / XHS -----------


def test_reddit_subreddit_and_user_pages_poll_their_native_rss(tmp_path: Path) -> None:
    """Reddit needs no adapter: subreddits and user pages have native RSS — the
    poll rewrites the page URL to it and the existing feed pipeline does the rest."""
    from app.tracking.poll import _fetch_url

    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(conn, input_url="https://www.reddit.com/r/investing/", mode="direct")
    assert _fetch_url(sub) == "https://www.reddit.com/r/investing/.rss"
    user = create_subscription(
        conn, input_url="https://reddit.com/user/someone", mode="homepage_diff"
    )
    assert _fetch_url(user) == "https://www.reddit.com/user/someone/.rss"
    # a single post is a one-item source, not a feed rewrite
    from app.tracking.poll import _is_single_content

    assert _is_single_content("https://www.reddit.com/r/investing/comments/abc12/title_here/")


def test_weibo_profile_lists_posts_via_the_mobile_endpoint(tmp_path: Path) -> None:
    """A Weibo profile URL polls the public mobile JSON endpoint through the
    injected fetch — posts land as items with text titles and status URLs."""
    import json as _json

    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(conn, input_url="https://weibo.com/u/1234567890", mode="direct")
    payload = {
        "ok": 1,
        "data": {
            "cards": [
                {
                    "card_type": 9,
                    "mblog": {
                        "id": "5001",
                        "bid": "OaBcDeF",
                        "created_at": "Fri Jul 10 09:30:00 +0800 2026",
                        "text": "<span>央行今日开展 2000 亿元逆回购操作</span>",
                    },
                },
                {"card_type": 58},  # a non-post card is skipped
            ]
        },
    }
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return _json.dumps(payload).encode()

    urls: list[str] = []

    def dispatch(s: Subscription, req: SourceRequest) -> None:
        urls.append(req.url or "")

    out = poll_subscription(conn, sub, fetch=fetch, dispatch=dispatch)
    assert out.ok and out.new_count == 1
    assert "containerid=1076031234567890" in fetched[0]
    assert urls == ["https://m.weibo.cn/status/OaBcDeF"]
    row = conn.execute("SELECT title FROM tracked_items").fetchone()
    assert row["title"] == "央行今日开展 2000 亿元逆回购操作"


def test_unsupported_platforms_fail_typed_with_an_honest_message(tmp_path: Path) -> None:
    """X/Twitter and Xiaohongshu PROFILES have no free login-less interface — the
    poll refuses with a clear message instead of a source that never produces."""
    conn = init_db(str(tmp_path / "daily.db"))

    def no_dispatch(s: Subscription, req: SourceRequest) -> None:
        raise AssertionError("nothing should dispatch")

    def no_fetch(_u: str) -> bytes:
        raise AssertionError("nothing should be fetched")

    for url in ("https://x.com/someone", "https://www.xiaohongshu.com/user/profile/abc"):
        sub = create_subscription(conn, input_url=url, mode="direct")
        out = poll_subscription(conn, sub, fetch=no_fetch, dispatch=no_dispatch)
        assert out.ok is False
        assert "暂不支持" in (out.error or "")


def test_douyin_and_xhs_single_videos_are_one_item_sources() -> None:
    from app.tracking.poll import _is_single_video

    assert _is_single_video("https://www.douyin.com/video/7350000000000000000")
    assert _is_single_video("https://v.douyin.com/abc123/")
    assert _is_single_video("https://www.xiaohongshu.com/explore/66aabbcc?xsec=1")
    assert _is_single_video("https://xhslink.com/xyz")
    assert not _is_single_video("https://www.douyin.com/user/MS4wLjABAAAA")


def test_watchlater_player_url_canonicalizes_to_the_video_page(tmp_path: Path) -> None:
    """Owner 2026-07-13: a 稍后再看 player link carries the video in `bvid=` —
    it is recognized as a single video and stored under the clean /video/ URL."""
    conn = init_db(str(tmp_path / "daily.db"))
    sub = create_subscription(
        conn,
        input_url=(
            "https://www.bilibili.com/list/watchlater/?bvid=BV1xgoHBLEjd"
            "&oid=116445941991273&spm_id_from=333.881.0.0"
        ),
        mode="platform",
    )
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return b"<html><head><title>Some video title</title></head></html>"

    urls, dispatch = _collect_dispatch()
    out = poll_subscription(conn, sub, fetch=fetch, dispatch=dispatch)
    assert out.ok and out.new_count == 1
    # everything downstream sees the canonical video page, not the player URL
    assert fetched == ["https://www.bilibili.com/video/BV1xgoHBLEjd/"]
    assert urls == ["https://www.bilibili.com/video/BV1xgoHBLEjd/"]
