"""M7.4 — platform feed rules (SSOT §6.1 step 3).

Deterministic URL→feed rules for YouTube / Substack / WordPress / Medium. Scope:
pattern rules only — no network (M7.7), no homepage-diff (M7.5), no dedup (M7.6).
URL-derivable rules need no HTML; the YouTube-handle and WordPress rules use the
page HTML the resolver supplies."""

from __future__ import annotations

from app.tracking.platform import platform_feed, youtube_channel_id

_YT_CHANNEL_PAGE = (
    '<html><head><link rel="canonical" '
    'href="https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw">'
    '<meta itemprop="channelId" content="UC_x5XG1OV2P6uZZ5FSM9Ttw"></head></html>'
)
_WORDPRESS_PAGE = (
    '<html><head><meta name="generator" content="WordPress 6.5.2">'
    '<link rel="stylesheet" href="/wp-content/themes/x/style.css"></head></html>'
)


def test_youtube_channel_url_is_derivable_without_html() -> None:
    assert (
        platform_feed("https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw")
        == "https://www.youtube.com/feeds/videos.xml?channel_id=UC_x5XG1OV2P6uZZ5FSM9Ttw"
    )


def test_youtube_handle_needs_html_for_channel_id() -> None:
    handle = "https://www.youtube.com/@GoogleDevelopers"
    # without the page HTML the channelId is unknown → no rule yet
    assert platform_feed(handle) is None
    # with the fetched page, the channelId is resolved → feed URL
    assert (
        platform_feed(handle, html=_YT_CHANNEL_PAGE)
        == "https://www.youtube.com/feeds/videos.xml?channel_id=UC_x5XG1OV2P6uZZ5FSM9Ttw"
    )


def test_youtube_c_and_user_paths_resolve_with_html() -> None:
    for path in ("/c/SomeName", "/user/SomeName"):
        assert (
            platform_feed(f"https://www.youtube.com{path}", html=_YT_CHANNEL_PAGE)
            == "https://www.youtube.com/feeds/videos.xml?channel_id=UC_x5XG1OV2P6uZZ5FSM9Ttw"
        )


def test_youtube_channel_tab_urls_resolve() -> None:
    # operators routinely copy a channel-tab URL (/videos, /streams, /featured, …)
    feed = "https://www.youtube.com/feeds/videos.xml?channel_id=UC_x5XG1OV2P6uZZ5FSM9Ttw"
    for path in (
        "/@GoogleDevelopers/videos",
        "/@GoogleDevelopers/streams",
        "/c/SomeName/videos",
        "/user/SomeName/featured",
        "/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw/videos",  # tab on a /channel/ URL too
    ):
        assert platform_feed(f"https://www.youtube.com{path}", html=_YT_CHANNEL_PAGE) == feed


def test_youtube_channel_id_extraction() -> None:
    assert youtube_channel_id(_YT_CHANNEL_PAGE) == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert youtube_channel_id("<html>no id here</html>") is None


def test_substack_rule() -> None:
    assert platform_feed("https://stratechery.substack.com/") == (
        "https://stratechery.substack.com/feed"
    )


def test_medium_user_and_subdomain_rules() -> None:
    assert platform_feed("https://medium.com/@someuser") == "https://medium.com/feed/@someuser"
    assert platform_feed("https://someuser.medium.com/") == "https://someuser.medium.com/feed"


def test_wordpress_detected_from_html_uses_feed_convention() -> None:
    assert platform_feed("https://blog.example.com/", html=_WORDPRESS_PAGE) == (
        "https://blog.example.com/feed/"
    )
    # /wp-content present even without a generator meta still detects WordPress
    assert (
        platform_feed("https://shop.example.com/", html='<link href="/wp-content/x.css">')
        == "https://shop.example.com/feed/"
    )


def test_non_platform_url_returns_none() -> None:
    assert platform_feed("https://www.federalreserve.gov/") is None
    # a generic site, even with HTML, is not WordPress → no rule
    assert platform_feed("https://www.example.com/", html="<html><body>plain</body></html>") is None
