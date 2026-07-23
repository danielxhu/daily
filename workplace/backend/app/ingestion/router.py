"""URL resolver / router core (M1A.3, SSOT §FR-2).

A pasted URL is resolved then routed before any extractor runs:

1. `resolve_url` — follow redirects (via an injected fetcher, so it's offline-
   testable) and `normalize_url`.
2. `normalize_url` — strip tracking params, lowercase scheme/host, drop fragment,
   and prefer the canonical over AMP/mobile variants. Pure function.
3. `sniff_kind` — route by **magic-bytes first** (servers mislabel `Content-Type`),
   falling back to the declared content-type: html / rss / audio / youtube /
   unknown. YouTube is a URL-pattern match. (PDF is sniffed as `unknown` here and
   handled in Stage 1B.)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

RouteKind = Literal["html", "rss", "audio", "youtube", "unknown"]

# Query params that never identify content — dropped on normalization.
TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "ref",
        "ref_src",
        "spm",
        "amp",
        "outputtype",  # ?outputType=amp
    }
)

_YOUTUBE_HOSTS = ("youtube.com", "youtu.be")


def _strip_host_prefix(host: str) -> str:
    """Drop a leading `m.` (mobile) or `amp.` (AMP) label when the remainder is
    still a valid multi-label host."""
    for prefix in ("m.", "amp."):
        if host.startswith(prefix):
            rest = host[len(prefix) :]
            if "." in rest:  # keep at least registrable-looking host
                return rest
    return host


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = _strip_host_prefix(parts.netloc.lower())

    path = parts.path
    # AMP path variants: /amp, /amp/, …/amp.html
    if path.endswith("/amp") or path.endswith("/amp/"):
        path = path[: path.rfind("/amp")] or "/"

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(sorted(kept))

    return urlunsplit((scheme, host, path, query, ""))  # fragment dropped


def is_youtube(url: str) -> bool:
    host = _strip_host_prefix(urlsplit(url).netloc.lower())
    host = host.removeprefix("www.").removeprefix("music.")
    return host in _YOUTUBE_HOSTS or host.endswith(".youtube.com")


def is_bilibili_video(url: str) -> bool:
    """A single Bilibili video page (owner 2026-07-10: B 站兼容). Content comes via
    the same yt-dlp caption/whisper path as YouTube — the raw page is a JS shell
    that the webpage extractor would reduce to junk. yt-dlp supports Bilibili
    natively (captions, audio, and its anti-crawl signing)."""
    parts = urlsplit(url)
    host = _strip_host_prefix(parts.netloc.lower()).removeprefix("www.")
    return host in ("bilibili.com", "b23.tv") and (
        parts.path.startswith("/video/") or "bvid=BV" in (parts.query or "") or host == "b23.tv"
    )


def is_xiaohongshu_note(url: str) -> bool:
    """A single Xiaohongshu note URL (or an xhslink short link to one). Routed
    with a page peek first (owner 2026-07-23): many notes are image/text posts
    with NO video, where yt-dlp fails deterministically ("No video formats
    found") while the note body sits in the page HTML."""
    parts = urlsplit(url)
    host = _strip_host_prefix(parts.netloc.lower()).removeprefix("www.").removeprefix("m.")
    return host == "xhslink.com" or (
        host == "xiaohongshu.com"
        and (parts.path.startswith("/explore/") or parts.path.startswith("/discovery/item/"))
    )


def is_video_platform(url: str) -> bool:
    """Any single-video/note page whose content must come via yt-dlp rather than
    the webpage extractor (owner 2026-07-10: 主流平台兼容): YouTube, Bilibili,
    Douyin videos, Xiaohongshu notes. Best-effort where the platform is hostile
    (Douyin/XHS rate-control hard) — a block is a typed failure, never junk text."""
    if is_youtube(url) or is_bilibili_video(url):
        return True
    parts = urlsplit(url)
    host = _strip_host_prefix(parts.netloc.lower()).removeprefix("www.").removeprefix("m.")
    if host == "v.douyin.com" or (host == "douyin.com" and parts.path.startswith("/video/")):
        return True
    return is_xiaohongshu_note(url)


def _looks_like_audio(b: bytes) -> bool:
    return (
        b.startswith(b"ID3")
        or b[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")  # MP3 frame sync
        or b.startswith(b"OggS")
        or (b[:4] == b"RIFF" and b[8:12] == b"WAVE")
        or b[4:8] == b"ftyp"  # MP4/M4A container
    )


def sniff_kind(
    head: bytes, *, declared_content_type: str | None = None, url: str | None = None
) -> RouteKind:
    if url and is_youtube(url):
        return "youtube"

    b = head[:1024]
    if b.startswith(b"%PDF"):
        return "unknown"  # PDF routed in Stage 1B, not an M1A.3 bucket
    if _looks_like_audio(b):
        return "audio"

    text = b.decode("utf-8", "ignore").lstrip("﻿ \t\r\n").lower()
    if "<rss" in text or "<feed" in text or "<atom" in text:
        return "rss"
    if text.startswith("<?xml") and ("rss" in text or "atom" in text or "feed" in text):
        return "rss"
    if "<!doctype html" in text or "<html" in text or "<head" in text:
        return "html"

    ct = (declared_content_type or "").lower()
    if "html" in ct:
        return "html"
    if "rss" in ct or "atom" in ct:
        return "rss"
    if ct.startswith("audio/"):
        return "audio"
    return "unknown"


@dataclass(frozen=True)
class Route:
    normalized_url: str
    kind: RouteKind


def route(url: str, *, head: bytes = b"", declared_content_type: str | None = None) -> Route:
    normalized = normalize_url(url)
    kind = sniff_kind(head, declared_content_type=declared_content_type, url=normalized)
    return Route(normalized_url=normalized, kind=kind)


def resolve_url(url: str, fetch_final_url: Callable[[str], str] | None = None) -> str:
    """Normalize, optionally following redirects first via an injected fetcher
    (the real one — httpx, M1A.4 — is mockable for offline tests)."""
    final = fetch_final_url(url) if fetch_final_url is not None else url
    return normalize_url(final)
