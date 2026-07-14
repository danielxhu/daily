"""M1A.3 — URL resolver / router core."""

from __future__ import annotations

import pytest

from app.ingestion.router import (
    is_youtube,
    normalize_url,
    resolve_url,
    route,
    sniff_kind,
)

# --- normalize_url ----------------------------------------------------------


def test_strips_tracking_params() -> None:
    out = normalize_url("https://example.com/a?utm_source=x&id=7&fbclid=abc")
    assert out == "https://example.com/a?id=7"


def test_drops_fragment_and_lowercases_host() -> None:
    assert normalize_url("https://Example.COM/a#section") == "https://example.com/a"


def test_mobile_and_amp_host_to_canonical() -> None:
    assert normalize_url("https://m.example.com/a") == "https://example.com/a"
    assert normalize_url("https://amp.example.com/a") == "https://example.com/a"


def test_amp_path_and_query_stripped() -> None:
    assert normalize_url("https://example.com/story/amp") == "https://example.com/story"
    assert normalize_url("https://example.com/x?amp=1&id=2") == "https://example.com/x?id=2"


def test_short_link_left_alone_when_no_resolver() -> None:
    # m. prefix on a 2-label host can't be safely stripped → kept
    assert normalize_url("https://m.co/abc") == "https://m.co/abc"


# --- is_youtube -------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc",
        "https://youtu.be/abc",
        "https://m.youtube.com/watch?v=abc",
        "https://music.youtube.com/watch?v=abc",
    ],
)
def test_is_youtube_true(url: str) -> None:
    assert is_youtube(url) is True


def test_is_youtube_false() -> None:
    assert is_youtube("https://example.com/watch?v=abc") is False


# --- sniff_kind (magic-bytes beat a lying Content-Type) ---------------------


def test_youtube_routes_by_url() -> None:
    assert sniff_kind(b"", url="https://youtu.be/abc") == "youtube"


def test_html_magic_beats_octet_stream_lie() -> None:
    assert (
        sniff_kind(b"<!doctype html><html>", declared_content_type="application/octet-stream")
        == "html"
    )


def test_rss_magic_beats_html_lie() -> None:
    body = b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
    assert sniff_kind(body, declared_content_type="text/html") == "rss"


def test_atom_feed_detected() -> None:
    assert sniff_kind(b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">') == "rss"


@pytest.mark.parametrize(
    "head",
    [b"ID3\x03\x00", b"\xff\xfb\x90\x00", b"OggS\x00\x02", b"RIFF\x00\x00\x00\x00WAVE"],
)
def test_audio_magic(head: bytes) -> None:
    assert sniff_kind(head) == "audio"


def test_pdf_is_unknown_in_1a() -> None:
    assert sniff_kind(b"%PDF-1.4") == "unknown"


def test_unknown_fallback() -> None:
    assert sniff_kind(b"\x00\x01\x02 random", declared_content_type=None) == "unknown"


def test_content_type_fallback_when_no_magic() -> None:
    assert sniff_kind(b"   plain text", declared_content_type="text/html") == "html"


# --- route + resolve_url ----------------------------------------------------


def test_route_combines_normalize_and_sniff() -> None:
    r = route(
        "https://m.example.com/a?utm_source=x",
        head=b"<html></html>",
        declared_content_type="text/plain",
    )
    assert r.normalized_url == "https://example.com/a"
    assert r.kind == "html"


def test_resolve_follows_injected_redirect_then_normalizes() -> None:
    redirects = {"https://sho.rt/x": "https://www.example.com/article?utm_source=t#top"}
    out = resolve_url("https://sho.rt/x", fetch_final_url=lambda u: redirects[u])
    assert out == "https://www.example.com/article"


def test_resolve_without_resolver_just_normalizes() -> None:
    assert resolve_url("https://example.com/a#x") == "https://example.com/a"


def test_bilibili_video_detection() -> None:
    from app.ingestion.router import is_bilibili_video

    assert is_bilibili_video("https://www.bilibili.com/video/BV14eRcBnEpE/?spm=x")
    assert is_bilibili_video("https://b23.tv/abc123")
    assert not is_bilibili_video("https://space.bilibili.com/2104838515")
    assert not is_bilibili_video("https://www.bilibili.com/read/cv123")
    assert not is_bilibili_video("https://example.com/video/BV1")


def test_video_platform_routing_matrix() -> None:
    from app.ingestion.router import is_video_platform

    assert is_video_platform("https://www.youtube.com/watch?v=abc")
    assert is_video_platform("https://www.bilibili.com/video/BV1x/")
    assert is_video_platform("https://www.douyin.com/video/7350000000000000000")
    assert is_video_platform("https://v.douyin.com/abc/")
    assert is_video_platform("https://www.xiaohongshu.com/explore/66aabbcc")
    assert not is_video_platform("https://m.weibo.cn/status/OaBcDeF")
    assert not is_video_platform("https://www.reddit.com/r/x/comments/1/y/")
    assert not is_video_platform("https://example.com/article")
