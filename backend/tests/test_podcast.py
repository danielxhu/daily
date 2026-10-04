"""M1A.5 — podcast/audio resolver: direct audio + RSS enclosure resolve;
Apple/Spotify pages typed-skip with a next step."""

from __future__ import annotations

import pytest

from app.ingestion.podcast import (
    enclosure_from_rss,
    is_direct_audio_url,
    is_unsupported_podcast_page,
    resolve_audio,
)
from tests import fixtures_loader as fx


@pytest.mark.parametrize(
    "url",
    ["https://cdn.example.com/ep1.mp3", "https://x.test/a/b.m4a", "https://x.test/c.OGG?token=1"],
)
def test_direct_audio_detected(url: str) -> None:
    assert is_direct_audio_url(url) is True


def test_non_audio_url_not_direct() -> None:
    assert is_direct_audio_url("https://example.com/article") is False


def test_resolve_direct_audio_url() -> None:
    res = resolve_audio("https://cdn.example.com/ep1.mp3")
    assert res.audio_url == "https://cdn.example.com/ep1.mp3"
    assert res.failure is None


def test_resolve_rss_enclosure() -> None:
    feed = fx.load_text("audio/podcast_rss.xml")
    res = resolve_audio("https://example.com/feed.xml", feed_text=feed)
    assert res.audio_url == "https://example.com/audio/ep1.mp3"
    assert res.failure is None


def test_rss_without_audio_enclosure_is_parse_empty() -> None:
    feed = '<?xml version="1.0"?><rss><channel><item><title>no audio</title></item></channel></rss>'
    res = resolve_audio("https://example.com/feed.xml", feed_text=feed)
    assert res.audio_url is None
    assert res.failure is not None and res.failure.kind == "parse_empty"
    assert res.failure.next_action  # has a next step


@pytest.mark.parametrize(
    "url",
    [
        "https://podcasts.apple.com/us/podcast/x/id123",
        "https://open.spotify.com/episode/abc",
        "https://music.apple.com/us/podcast/x",
    ],
)
def test_apple_spotify_pages_typed_skip(url: str) -> None:
    assert is_unsupported_podcast_page(url) is True
    res = resolve_audio(url)
    assert res.audio_url is None
    assert res.failure is not None
    assert res.failure.kind == "unsupported_file"
    assert res.failure.type == "podcast"
    assert res.failure.next_action  # user gets a next step (RSS / direct audio)


def test_unresolvable_page_without_feed_is_typed_skip() -> None:
    res = resolve_audio("https://example.com/some-podcast-landing")
    assert res.audio_url is None
    assert res.failure is not None and res.failure.kind == "unsupported_file"


def test_enclosure_parser_handles_bad_xml() -> None:
    assert enclosure_from_rss("not xml <<<") is None
