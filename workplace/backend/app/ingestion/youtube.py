"""YouTube caption path (M1A.7, SSOT §FR-2 / §10).

Captions via `yt-dlp` (primary), with local-whisper audio fallback in M1A.8. This
module finds a caption track (manual subtitles preferred over automatic), fetches
the VTT through the X0.8 fetch policy, and parses it to `TranscriptResult` segments.
Both English and Chinese tracks are handled (NFR-5). `yt-dlp` is heavy + network,
so it is lazy-imported and the extractor is injectable for offline tests (NFR-3).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.clients.base import TranscriptResult, TranscriptSegment
from app.ingestion.fetch_policy import FETCH_TIMEOUT_MS

# English first (claim output is English by default, NFR-5), then Chinese variants.
PREFERRED_LANGS = ("en", "en-US", "en-GB", "zh", "zh-Hans", "zh-CN", "zh-Hant", "zh-TW")


@dataclass(frozen=True)
class CaptionChoice:
    lang: str
    url: str
    ext: str
    is_auto: bool


def _pick_format(tracks: list[dict[str, Any]], prefer_ext: str = "vtt") -> dict[str, Any] | None:
    for t in tracks:
        if t.get("ext") == prefer_ext and t.get("url"):
            return t
    for t in tracks:
        if t.get("url"):
            return t
    return None


def select_caption(info: dict[str, Any], *, prefer_ext: str = "vtt") -> CaptionChoice | None:
    """Pick a caption track: manual subtitles before automatic, then by language
    preference. None when no EN/ZH track exists (→ audio fallback, M1A.8)."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    for is_auto, source in ((False, manual), (True, auto)):
        for lang in PREFERRED_LANGS:
            tracks = source.get(lang)
            if not tracks:
                continue
            track = _pick_format(tracks, prefer_ext)
            if track:
                return CaptionChoice(
                    lang=lang, url=track["url"], ext=track.get("ext", ""), is_auto=is_auto
                )
    return None


def _vtt_ts_ms(ts: str) -> int:
    ts = ts.replace(",", ".")
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


_TIMING_RE = re.compile(r"(\d\d:\d\d:\d\d[.,]\d{3})\s*-->\s*(\d\d:\d\d:\d\d[.,]\d{3})")
_TAG_RE = re.compile(r"<[^>]+>")


def parse_vtt(text: str) -> list[TranscriptSegment]:
    """Parse WebVTT cues → segments (ms). Caption cues have no word timestamps."""
    segments: list[TranscriptSegment] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        timing_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing_idx is None:
            continue
        m = _TIMING_RE.search(lines[timing_idx])
        if not m:
            continue
        cue_lines = [ln for ln in lines[timing_idx + 1 :] if ln.strip()]
        cue_text = _TAG_RE.sub("", " ".join(cue_lines)).strip()
        if cue_text:
            segments.append(
                TranscriptSegment(
                    text=cue_text,
                    start_ms=_vtt_ts_ms(m.group(1)),
                    end_ms=_vtt_ts_ms(m.group(2)),
                )
            )
    return segments


def yt_dlp_opts() -> dict[str, object]:
    """`YoutubeDL` params bound to the X0.8 fetch policy (metadata fetch is a
    network path too, so it must obey the same red lines as httpx).

    Param names/semantics verified against yt-dlp's `YoutubeDL` source:
    - `proxy=""` → yt-dlp maps an empty proxy to `__noproxy__` (direct connection)
      and, because it is not None, **does NOT fall through to env `HTTP(S)_PROXY`/
      `ALL_PROXY`** — the env-proxy equivalent of httpx `trust_env=False` (§2.2).
    - `cookiefile=None` / `cookiesfrombrowser=None` → never load user cookies/session.
    - `usenetrc=False` → never read `~/.netrc` credentials.
    - `geo_bypass=False` → no X-Forwarded-For geo-evasion (§2.2 no fingerprint evasion).
    - `skip_download=True` → metadata only, never download media here.
    - `noplaylist=True` → a single video, never expand playlists.
    """
    return {
        "skip_download": True,
        "quiet": True,
        "noplaylist": True,
        "proxy": "",
        "cookiefile": None,
        "cookiesfrombrowser": None,
        "usenetrc": False,
        "geo_bypass": False,
        "socket_timeout": FETCH_TIMEOUT_MS / 1000,
    }


def extract_info(
    url: str, *, extractor: Callable[[str], dict[str, Any]] | None = None
) -> dict[str, Any]:
    """yt-dlp metadata for a video (no download). `extractor` is injectable so the
    offline suite never imports yt-dlp."""
    if extractor is not None:
        return extractor(url)
    from yt_dlp import YoutubeDL  # lazy: heavy + network

    with YoutubeDL(yt_dlp_opts()) as ydl:
        return ydl.extract_info(url, download=False)  # type: ignore[no-any-return]


def fetch_captions(
    url: str,
    *,
    client: httpx.Client,
    extractor: Callable[[str], dict[str, Any]] | None = None,
) -> TranscriptResult | None:
    """Find + fetch + parse a YouTube caption track. None when there is no usable
    caption (the caller then tries the audio fallback, M1A.8)."""
    info = extract_info(url, extractor=extractor)
    choice = select_caption(info)
    if choice is None:
        return None
    resp = client.get(choice.url)
    resp.raise_for_status()
    segments = parse_vtt(resp.text)
    if not segments:
        return None
    return TranscriptResult(language=choice.lang, segments=segments)
