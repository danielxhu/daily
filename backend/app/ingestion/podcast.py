"""Podcast / audio resolver (M1A.5, SSOT §FR-2).

Resolves a podcast/audio source to a **direct audio URL** the transcriber (M1A.6)
can consume — either the URL is itself a direct audio file, or it's an RSS feed
whose first audio `<enclosure>` we take. V1 deliberately does **not** promise that
arbitrary Apple Podcasts / Spotify *web pages* resolve (no app-internal scraping);
those are a typed skip with a next step (§FR-2 / §6.6).

This resolver does not fetch by itself — the caller passes already-fetched RSS text
(routed as `rss` by M1A.3), keeping it pure and offline-testable. Feed parsing here
is a minimal stdlib enclosure scan; the full feed parser (feedparser) lands at M7.2.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.ingestion.fetch_policy import typed_skip
from app.schemas.models import SourceFailure

AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".ogg", ".oga", ".wav", ".flac", ".opus")

# Podcast platform *web pages* we don't resolve to audio in V1.
_UNSUPPORTED_HOSTS = frozenset(
    {"podcasts.apple.com", "music.apple.com", "open.spotify.com", "spotify.com"}
)


@dataclass(frozen=True)
class AudioResolution:
    audio_url: str | None  # resolved direct audio URL (→ transcribe, M1A.6)
    failure: SourceFailure | None  # set when the source can't be resolved


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _is_audio_path(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(AUDIO_EXTS)


def is_direct_audio_url(url: str) -> bool:
    return _is_audio_path(url)


def is_unsupported_podcast_page(url: str) -> bool:
    host = _host(url)
    return host in _UNSUPPORTED_HOSTS or host.endswith(".spotify.com")


def enclosure_from_rss(feed_text: str) -> str | None:
    """First audio `<enclosure>` URL in an RSS feed, or None."""
    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError:
        return None
    for el in root.iter():
        if el.tag.split("}")[-1].lower() != "enclosure":
            continue
        url = el.get("url")
        mime = (el.get("type") or "").lower()
        if url and (mime.startswith("audio/") or _is_audio_path(url)):
            return url
    return None


def resolve_audio(url: str, *, feed_text: str | None = None) -> AudioResolution:
    """Resolve `url` (+ optional already-fetched RSS `feed_text`) to a direct audio
    URL, or a typed failure with a next step."""
    if is_unsupported_podcast_page(url):
        return AudioResolution(
            audio_url=None,
            failure=typed_skip(
                "unsupported_file",
                reason=(
                    "Apple Podcasts / Spotify web pages aren't resolved in V1 — "
                    "use the podcast's RSS feed or a direct audio URL."
                ),
                requested_url=url,
                source_type="podcast",
            ),
        )
    if is_direct_audio_url(url):
        return AudioResolution(audio_url=url, failure=None)
    if feed_text is not None:
        enclosure = enclosure_from_rss(feed_text)
        if enclosure is not None:
            return AudioResolution(audio_url=enclosure, failure=None)
        return AudioResolution(
            audio_url=None,
            failure=typed_skip(
                "parse_empty",
                reason="No audio <enclosure> found in the feed.",
                requested_url=url,
                source_type="podcast",
            ),
        )
    return AudioResolution(
        audio_url=None,
        failure=typed_skip(
            "unsupported_file",
            reason="Could not resolve a direct audio URL or RSS enclosure.",
            requested_url=url,
            source_type="podcast",
        ),
    )
